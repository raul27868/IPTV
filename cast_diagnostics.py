"""Safe, actionable diagnostics for IPTV source, FFmpeg and Cast playback.

A HEAD preflight never downloads video. Most provider failures are only
confirmed by the actual FFmpeg/receiver request; HEAD is advisory unless it
explicitly reports a transient origin 5xx status.
"""
from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request


class SourceUnavailable(RuntimeError):
    """Confirmed upstream HTTP failure; message never contains a private URL."""

    def __init__(self, code: int):
        self.code = int(code)
        super().__init__(f"Servidor IPTV: HTTP {self.code}. El canal no está disponible ahora.")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def preflight_source(url: str, *, timeout: float = 3.0, opener=None):
    """Try one lightweight HEAD (no stream body) before costly transcoding.

    Reject only explicit 502/503/504: these are meaningful provider outages.
    A 405, 403, timeout or redirect is inconclusive because many Xtream
    services don't implement HEAD like GET. Let FFmpeg make its real request.
    Never issue GET here and never include URLs in diagnostics.
    """
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        return "omitted"
    req = urllib.request.Request(url, method="HEAD",
                                 headers={"User-Agent": "IPTV-Video/15.0"})
    client = opener or urllib.request.build_opener(_NoRedirect())
    try:
        with client.open(req, timeout=timeout) as reply:
            status = getattr(reply, "status", None)
            if status in (502, 503, 504):
                raise SourceUnavailable(status)
            return "reachable" if status == 200 else "inconclusive"
    except urllib.error.HTTPError as exc:
        if exc.code in (502, 503, 504):
            raise SourceUnavailable(exc.code) from None
        return "inconclusive"
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return "inconclusive"


def ffmpeg_diagnosis(stderr: str) -> tuple[str, str]:
    """Classify without quoting stderr: it may contain Xtream credentials."""
    text = (stderr or "").lower()
    code = re.search(r"(?:http error|server returned|http/1\.[01]|http/2)\s*(?:[^0-9]{0,15})?(40[01345]|50[0-9])\b", text)
    if code:
        status = int(code.group(1))
        if status in (502, 503, 504):
            return ("origin", f"Servidor IPTV: HTTP {status}. El canal no está disponible en este momento.")
        if status in (401, 403):
            return ("origin", f"Servidor IPTV: HTTP {status}. Acceso rechazado; comprueba el perfil o el límite de conexiones.")
        if status in (404, 410):
            return ("origin", f"Servidor IPTV: HTTP {status}. El enlace del canal no está disponible.")
        return ("origin", f"Servidor IPTV: HTTP {status}. No se pudo abrir el canal.")
    if any(phrase in text for phrase in (
        "decoder not found", "unknown decoder", "unsupported codec",
        "codec not currently supported", "video codec not supported",
        "audio codec not supported", "could not find codec parameters",
    )):
        return ("codec", "FFmpeg no puede interpretar el códec/formato del canal.")
    if any(phrase in text for phrase in (
        "connection refused", "connection timed out", "network is unreachable",
        "connection reset by peer", "failed to resolve hostname",
    )):
        return ("network", "La conexión con el servidor IPTV ha fallado.")
    return ("ffmpeg", "FFmpeg no ha podido convertir el canal a HLS. Consulta Diagnóstico para más datos.")


def cast_receiver_diagnosis(state: str, reason: str) -> tuple[str, str]:
    """Cast cannot prove a codec failure from IDLE/ERROR alone."""
    state = (state or "").upper()
    reason = (reason or "").upper()
    if state == "IDLE" and reason in ("ERROR", "LOAD_FAILED"):
        return ("receiver", "Chromecast ha rechazado la reproducción. Posibles causas: formato/códec no admitido, URL inaccesible o error del receptor.")
    if state == "IDLE" and reason == "CANCELLED":
        return ("cancelled", "Chromecast ha cancelado la reproducción.")
    return ("unconfirmed", "Chromecast aún no confirma la reproducción; comprueba el televisor.")


def playback_mode_label(requested_direct: bool, mime: str | None) -> tuple[bool, str]:
    """Return (requires_transcoding, visible effective playback mode)."""
    if not requested_direct:
        return True, "Compatible (FFmpeg/HLS) · seleccionado"
    if mime in (None, "video/mp2t"):
        reason = "MPEG-TS" if mime == "video/mp2t" else "formato desconocido"
        return True, f"Directo → Compatible automáticamente ({reason})"
    return False, "Directo (Chromecast recibe la URL)"
