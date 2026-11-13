"""VOD diagnostics: bounded metrics, no URLs, credentials or title metadata.

Designed to export session summaries even after playback has stopped.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import json
import re
import time

KNOWN_MEDIA = {"live", "movie", "episode", "unknown"}
KNOWN_MODES = {"direct", "hls-standard", "hls-stable", "hls-light", "local"}
SAMPLE_LIMIT = 720
HTTP_CODES = {200, 206, 400, 401, 403, 404, 408, 429, 500, 502, 503, 504}


def content_kind(item) -> str:
    attrs = getattr(item, "attributes", {}) or {}
    explicit = attrs.get("iptv_media_kind")
    if explicit in KNOWN_MEDIA:
        return explicit
    group = (getattr(item, "group", "") or "").lower()
    if group == "xtream películas":
        return "movie"
    if group == "xtream episodio":
        return "episode"
    if group == "xtream tv":
        return "live"
    return "unknown"


def cast_stream_type(kind: str, *, transcoded: bool) -> str:
    # Sliding HLS is a live playlist, including when its *source* is VOD.
    # Only direct VOD can safely advertise a seekable/buffered resource.
    return "LIVE" if transcoded or kind not in ("movie", "episode") else "BUFFERED"


def parse_ffmpeg_progress(path: Path | None) -> dict:
    """Read FFmpeg progress file, selecting numeric-only fields."""
    if path is None:
        return {}
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")[-4500:]
    except OSError:
        return {}
    parts = raw.rsplit("progress=", 1)
    text = parts[-1] if len(parts) > 1 else raw
    values = {}
    for line in text.splitlines():
        if "=" in line:
            key, value = line.strip().split("=", 1)
            if key in ("speed", "fps", "out_time_ms", "out_time_us", "total_size", "frame"):
                values[key] = value
    result = {}
    for key in ("fps", "speed", "frame"):
        val = values.get(key, "").rstrip("x")
        try:
            number = float(val)
            if number >= 0 and number < 100000000:
                result[key] = round(number, 3)
        except ValueError:
            pass
    try:
        result["output_seconds"] = round(max(0, int(values.get("out_time_us", "0"))) / 1000000, 2)
    except ValueError:
        pass
    return result


@dataclass
class VODSessionReport:
    kind: str
    mode: str
    started_at: float = field(default_factory=time.time)
    samples: list[dict] = field(default_factory=list)
    responses: Counter = field(default_factory=Counter)
    last_cause: str | None = None
    interruptions: list[dict] = field(default_factory=list)
    ended_at: float | None = None

    def record_response(self, code: int):
        try:
            code = int(code)
        except (ValueError, TypeError):
            return
        self.responses[str(code) if code in HTTP_CODES else "other"] += 1

    def sample(self, *, snapshot=None, state="UNKNOWN", position=None, progress=None, elapsed=None):
        if len(self.samples) >= SAMPLE_LIMIT:
            self.samples.pop(0)
        entry = {
            "elapsed_s": round(max(0, elapsed or 0), 1),
            "receiver_state": str(state).upper() if str(state).upper() in
                              {"PLAYING", "BUFFERING", "PAUSED", "IDLE", "UNKNOWN"} else "UNKNOWN",
        }
        if isinstance(position, (float, int)) and 0 <= position < 1e9:
            entry["receiver_position_s"] = round(float(position), 1)
        if snapshot is not None:
            for key in ("latest_segment_age", "last_playlist_request_age", "last_segment_request_age"):
                value = getattr(snapshot, key, None)
                entry[key + "_s"] = round(value, 1) if isinstance(value, (float, int)) else None
            entry["ffmpeg_running"] = bool(snapshot.ffmpeg_running)
        if progress:
            entry["ffmpeg"] = {k: v for k, v in progress.items()
                               if k in ("speed", "fps", "frame", "output_seconds") and
                               isinstance(v, (int, float))}
        self.samples.append(entry)

    def finish(self, tracker=None):
        if self.ended_at is not None:
            return
        self.ended_at = time.time()
        if tracker is not None:
            self.interruptions = [
                {"cause": event.cause, "duration_s": round(event.duration, 1),
                 "recovery": event.recovery}
                for event in tracker.events[-100:]
            ]

    def to_dict(self):
        return {
            "schema": "iptv-vod-diagnostics-v1",
            "kind": self.kind if self.kind in KNOWN_MEDIA else "unknown",
            "mode": self.mode if self.mode in KNOWN_MODES else "direct",
            "started_utc": datetime.fromtimestamp(self.started_at, timezone.utc).isoformat(),
            "ended_utc": datetime.fromtimestamp(self.ended_at, timezone.utc).isoformat()
                         if self.ended_at is not None else None,
            "http_response_counts": dict(sorted(self.responses.items())),
            "interruptions": self.interruptions,
            "samples": self.samples,
            "notes": [
                "Network/FFmpeg/Cast telemetry does not prove visible video frames advance.",
                "HTTP response counters reflect local HLS requests, not provider responses.",
                "No stream URL, credentials, channel title, receiver IP or provider name is stored.",
            ],
        }

    def write(self, filename):
        destination = Path(filename)
        destination.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
                               encoding="utf-8")
