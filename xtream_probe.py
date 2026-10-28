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

def probe_catalog(server, username, password, *, fetcher=_fetch):
    """Return structural counts only. Collection responses have a 6 MB safety limit."""
    base = normalize_server(server)
    report = {"format":"iptv-xtream-catalog-v1",
              "timestamp_utc":datetime.now(timezone.utc).isoformat(),
              "collections":{}, "errors":[]}
    for action, name in (("get_live_streams","tv"),("get_vod_streams","movies"),
                         ("get_series","series")):
        try:
            items = fetcher(base,username,password,action=action,timeout=35)
            if not isinstance(items,list):
                raise XtreamError("La respuesta no contiene una lista.")
            report["collections"][name] = {
                "available":True, "count":len(items),
                "with_category_id":sum(isinstance(x,dict) and bool(x.get("category_id")) for x in items),
                "with_name":sum(isinstance(x,dict) and bool(x.get("name") or x.get("title")) for x in items)}
        except XtreamError as exc:
            report["collections"][name] = {"available":False,"error":str(exc)}
    return report
