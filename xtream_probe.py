"""Xtream Codes compatibility probe. No playback URLs or credentials in reports."""
from __future__ import annotations

import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

MAX_BYTES = 6 * 1024 * 1024
ACTIONS = ("get_live_categories", "get_vod_categories", "get_series_categories")
SAFE_CATEGORY_FIELDS = {"category_name", "parent_id"}


class XtreamError(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def normalize_server(server):
    raw = (server or "").strip().rstrip("/")
    if not raw:
        raise XtreamError("Introduce la URL del servidor.")
    if not re.match(r"^https?://", raw, re.I):
        raw = "http://" + raw
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise XtreamError("URL del servidor no válida.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise XtreamError("Usa solo el servidor y puerto, sin usuario, clave ni parámetros.")
    path = parsed.path.rstrip("/")
    if path.lower().endswith("/player_api.php"):
        path = path[:-len("/player_api.php")]
    if path and path != "/":
        raise XtreamError("Indica la URL base del servidor, sin rutas adicionales.")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def _fetch(server, username, password, action=None, timeout=12):
    if not username or not password:
        raise XtreamError("Faltan usuario o contraseña.")
    params = {"username": username, "password": password}
    if action:
        params["action"] = action
    url = server + "/player_api.php?" + urllib.parse.urlencode(params)
    opener = urllib.request.build_opener(_NoRedirect())
    req = urllib.request.Request(url, headers={"User-Agent": "IPTV-Video-Xtream-Probe/1.0",
                                               "Accept": "application/json"})
    try:
        with opener.open(req, timeout=timeout) as reply:
            if reply.status != 200:
                raise XtreamError("Respuesta HTTP inesperada.")
            payload = reply.read(MAX_BYTES + 1)
    except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
        # Never print exception: it can contain the URL with credentials.
        raise XtreamError("No se pudo conectar con la API Xtream (red, certificado o respuesta HTTP).") from None
    if len(payload) > MAX_BYTES:
        raise XtreamError("La respuesta excede el límite de seguridad de 6 MB.")
    try:
        return json.loads(payload.decode("utf-8-sig"))
    except (ValueError, UnicodeError):
        raise XtreamError("La respuesta no es JSON válido.") from None


def probe(server, username, password, *, fetcher=_fetch):
    """Make four lightweight requests. Return a shareable, credential-free report."""
    base = normalize_server(server)
    report = {
        "format": "iptv-xtream-probe-v1",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "connection": {"api_reachable": False, "authenticated": False},
        "categories": {},
        "errors": [],
    }
    try:
        info = fetcher(base, username, password)
        if not isinstance(info, dict):
            raise XtreamError("Respuesta de autenticación inesperada.")
        user = info.get("user_info")
        server_info = info.get("server_info")
        report["connection"]["api_reachable"] = True
        if isinstance(user, dict):
            auth = str(user.get("auth", "0")) == "1"
            report["connection"]["authenticated"] = auth
            # Only allowlist harmless scalar values. Do not leak username,
            # password, server URL, ports, playlist URLs or account identifiers.
            report["connection"]["user_status"] = str(user.get("status", "unknown"))[:32]
        report["connection"]["has_server_info"] = isinstance(server_info, dict)
        if not report["connection"]["authenticated"]:
            report["errors"].append("Autenticación no confirmada.")
            return report
    except XtreamError as exc:
        report["errors"].append(str(exc))
        return report
    for action, label in zip(ACTIONS, ("tv", "movies", "series")):
        try:
            data = fetcher(base, username, password, action=action)
            if not isinstance(data, list):
                raise XtreamError("Formato de categorías inesperado.")
            # Names could expose provider-specific info, so do not include
            # them in the shared diagnostic. Count only safe structural facts.
            report["categories"][label] = {
                "available": True,
                "count": len(data),
                "with_name": sum(1 for x in data if isinstance(x, dict) and bool(x.get("category_name"))),
                "with_parent": sum(1 for x in data if isinstance(x, dict) and str(x.get("parent_id", "0")) not in ("0", "", "None")),
            }
        except XtreamError as exc:
            report["categories"][label] = {"available": False, "error": str(exc)}
    return report


def save_report(report, path):
    """Caller chooses explicit destination; report never contains secrets."""
    Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def _stream_collection(server, username, password, action, *, series_id=None, timeout=45):
    """Stream a response directly from the server; never log credential-bearing URLs."""
    params = {"username": username, "password": password, "action": action}
    if series_id is not None:
        if not str(series_id).isdigit():
            raise XtreamError("Identificador de serie no válido.")
        params["series_id"] = str(series_id)
    url = server + "/player_api.php?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={
        "User-Agent": "IPTV-Video-Xtream-Probe/1.1", "Accept": "application/json"})
    try:
        return urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout)
    except (urllib.error.URLError, OSError, ValueError):
        raise XtreamError("No se pudo obtener el catálogo Xtream.") from None


def probe_catalog(server, username, password, *, fetcher=None):
    """Count content by streaming JSON; only export aggregate structural information."""
    from xtream_stream import iter_json_array
    base = normalize_server(server)
    report = {"format": "iptv-xtream-catalog-v2",
              "timestamp_utc": datetime.now(timezone.utc).isoformat(),
              "collections": {}, "series_sample": {"available": False}, "errors": []}

    valid_categories = {}
    for media, cat_action in (("tv","get_live_categories"),("movies","get_vod_categories"),
                              ("series","get_series_categories")):
        try:
            values = (_fetch(base,username,password,action=cat_action)
                      if fetcher is None else fetcher(base,username,password,action=cat_action,timeout=15))
            valid_categories[media] = {str(v["category_id"]) for v in values
                                       if isinstance(v,dict) and v.get("category_id") is not None}
        except (XtreamError,TypeError,KeyError):
            valid_categories[media] = None

    for action, name in (("get_live_streams", "tv"), ("get_vod_streams", "movies"),
                         ("get_series", "series")):
        counts = {"available": True, "count": 0, "with_category_id": 0,
                  "with_name": 0, "distinct_category_ids": 0, "valid_category_count": 0, "unknown_category_count": 0}
        categories = set()
        sample_id = None
        try:
            if fetcher is None:
                with _stream_collection(base, username, password, action) as reply:
                    for item in iter_json_array(reply):
                        if not isinstance(item, dict):
                            continue
                        counts["count"] += 1
                        category_id = item.get("category_id")
                        if category_id not in (None, ""):
                            counts["with_category_id"] += 1
                            categories.add(str(category_id))
                            if valid_categories[name] is not None:
                                key = "valid_category_count" if str(category_id) in valid_categories[name] else "unknown_category_count"
                                counts[key] += 1
                        if item.get("name") or item.get("title"):
                            counts["with_name"] += 1
                        if name == "series" and sample_id is None:
                            value = item.get("series_id")
                            if str(value).isdigit():
                                sample_id = value
            else:
                # Test injection maintains the same safe counting logic.
                items = fetcher(base, username, password, action=action, timeout=45)
                if not isinstance(items, list):
                    raise XtreamError("La colección no es una lista JSON.")
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    counts["count"] += 1
                    value = item.get("category_id")
                    if value not in (None, ""):
                        counts["with_category_id"] += 1
                        categories.add(str(value))
                        if valid_categories[name] is not None:
                            key = "valid_category_count" if str(value) in valid_categories[name] else "unknown_category_count"
                            counts[key] += 1
                    if item.get("name") or item.get("title"):
                        counts["with_name"] += 1
                    if name == "series" and sample_id is None and str(item.get("series_id")).isdigit():
                        sample_id = item["series_id"]
            counts["distinct_category_ids"] = len(categories)
            counts["category_ids_validated"] = valid_categories[name] is not None
            report["collections"][name] = counts
        except XtreamError as exc:
            report["collections"][name] = {"available": False, "error": str(exc)}
            continue
        except (OSError, ValueError, UnicodeError):
            report["collections"][name] = {"available": False, "error": "No se pudo procesar la colección."}
            continue

        if name == "series" and sample_id is not None:
            try:
                if fetcher is None:
                    details = _fetch_series_info(base, username, password, sample_id)
                else:
                    details = fetcher(base, username, password, action="get_series_info",
                                      series_id=sample_id, timeout=25)
                episodes = details.get("episodes") if isinstance(details, dict) else None
                if not isinstance(episodes, dict):
                    raise XtreamError("No hay estructura de episodios por temporada.")
                report["series_sample"] = {
                    "available": True,
                    "seasons_count": len(episodes),
                    "episode_count": sum(len(v) for v in episodes.values() if isinstance(v, list)),
                    "with_episode_lists": sum(isinstance(v, list) for v in episodes.values())
                }
            except XtreamError as exc:
                report["series_sample"] = {"available": False, "error": str(exc)}
    return report


def _fetch_series_info(server, username, password, series_id):
    """Fetch a single series details document with a bounded response."""
    with _stream_collection(server, username, password, "get_series_info",
                            series_id=series_id, timeout=25) as reply:
        raw = reply.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise XtreamError("La ficha de la serie supera 8 MB.")
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeError):
        raise XtreamError("La ficha de la serie no contiene JSON válido.") from None
