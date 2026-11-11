"""Conservative, read-only assessment of long-running Chromecast HLS sessions.

No automatic restarts: warn only after an initial grace period and sustained
lack of activity. Receiving PLAYING from Cast is not proof of decoded video.
"""
from __future__ import annotations

from cast_bridge import HLSSnapshot

GRACE_SECONDS = 45.0
STALE_SEGMENT_SECONDS = 30.0
STALE_REQUEST_SECONDS = 40.0


def assess_hls(snapshot: HLSSnapshot, *, elapsed: float, cast_state: str = "") -> tuple[str, str]:
    """Return (status_code, short user-readable assessment)."""
    if not snapshot.ffmpeg_running:
        return "source_stopped", "FFmpeg se ha detenido: el flujo IPTV/HLS ya no se genera."
    if elapsed < GRACE_SECONDS:
        return "initializing", "Monitor HLS: estabilizando la emisión."
    if snapshot.latest_segment_age is None or snapshot.latest_segment_age > STALE_SEGMENT_SECONDS:
        return "source_stalled", "HLS detenido: FFmpeg no genera segmentos recientes."
    if (snapshot.last_segment_request_age is None or
            snapshot.last_segment_request_age > STALE_REQUEST_SECONDS):
        return "receiver_stalled", "Chromecast lleva demasiado tiempo sin solicitar segmentos HLS."
    state = (cast_state or "").upper()
    if state == "IDLE":
        return "receiver_idle", "Chromecast está inactivo, aunque FFmpeg continúa generando vídeo."
    if state == "BUFFERING":
        return "receiver_buffering", "Chromecast está esperando búfer; FFmpeg continúa generando vídeo."
    return "healthy", "HLS activo: FFmpeg genera segmentos y Chromecast los solicita."


def format_age(value: float | None) -> str:
    return "sin solicitudes" if value is None else f"hace {int(value)} s"
