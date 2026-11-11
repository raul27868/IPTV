"""Local, single-session HLS transcoding bridge for Google Cast.

The ephemeral HTTP server serves only the random-token HLS directory.
Only use with streams you are permitted to play/retransmit on your LAN.
"""
from __future__ import annotations

import functools
import http.server
import logging
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass

from cast_diagnostics import SourceUnavailable, preflight_source, ffmpeg_diagnosis

LOG = logging.getLogger('iptv-video')


class BridgeStartError(RuntimeError):
    def __init__(self, category: str, explanation: str):
        super().__init__(explanation)
        self.category = category



@dataclass(frozen=True)
class HLSSnapshot:
    ffmpeg_running: bool
    latest_segment_age: float | None
    last_playlist_request_age: float | None
    last_segment_request_age: float | None
    latest_segment_name: str | None


HLS_PROFILES = {
    "standard": (2, 6, 3),
    "stable": (3, 12, 8),
}


class HLSBridge:
    def __init__(self, stream_url: str, cast_ip: str, *, profile: str = "standard"):
        if profile not in HLS_PROFILES:
            raise ValueError("Perfil HLS no válido")
        self.profile = profile
        self._last_playlist_request = None
        self._last_segment_request = None
        self._last_segment_name = None
        self._telemetry_lock = threading.Lock()
        self.cast_ip = cast_ip
        self.directory = Path(tempfile.mkdtemp(prefix='iptv-cast-'))
        self.token = secrets.token_urlsafe(22)
        self.stream_dir = self.directory / self.token
        self.stream_dir.mkdir(mode=0o700)
        self.process = None
        self.httpd = None
        self.thread = None
        self.stream_url = stream_url
        self._log_file = None
        self._stopped = False

    def snapshot(self) -> HLSSnapshot:
        """Observe HLS segment generation and Cast requests without private URLs."""
        now = time.monotonic()
        with self._telemetry_lock:
            playlist_at = self._last_playlist_request
            segment_at = self._last_segment_request
            segment_name = self._last_segment_name
        try:
            newest = max(self.stream_dir.glob("part_*.ts"), key=lambda p: p.stat().st_mtime)
            age = max(0.0, time.time() - newest.stat().st_mtime)
        except (ValueError, OSError):
            age = None
        return HLSSnapshot(
            ffmpeg_running=self.process is not None and self.process.poll() is None,
            latest_segment_age=age,
            last_playlist_request_age=(max(0.0, now - playlist_at) if playlist_at is not None else None),
            last_segment_request_age=(max(0.0, now - segment_at) if segment_at is not None else None),
            latest_segment_name=segment_name,
        )

    @staticmethod
    def lan_ip_for(peer: str) -> str:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect((peer, 8009))
            return sock.getsockname()[0]

    def start(self, timeout: int = 28) -> str:
        if not shutil.which('ffmpeg'):
            raise RuntimeError('No se encuentra FFmpeg: sudo apt install ffmpeg')
        try:
            # HEAD does not download video; unsupported requests are inconclusive.
            try:
                preflight_source(self.stream_url)
            except SourceUnavailable as exc:
                raise BridgeStartError("origin", str(exc)) from None
            local_ip = self.lan_ip_for(self.cast_ip)
            # Serve only playlist/segments from this session; avoid directory listings.
            base = self.directory.resolve()
            bridge_ref = self
            class Handler(http.server.SimpleHTTPRequestHandler):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, directory=str(base), **kwargs)
                def list_directory(self, path):
                    self.send_error(403)
                    return None
                def log_message(self, format, *args):
                    kind = 'playlist' if self.path.split('?')[0].endswith('.m3u8') else ('segment' if self.path.split('?')[0].endswith('.ts') else 'other')
                    LOG.info('HLS solicitud TV: cliente=%s recurso=%s respuesta=%s',
                             self.client_address[0], kind, args[1] if len(args) > 1 else '?')
                def do_GET(self):
                    from urllib.parse import unquote, urlsplit
                    path = unquote(urlsplit(self.path).path)
                    prefix = "/" + bridge_ref.token + "/"
                    self._monitor_requested_name = (
                        path[len(prefix):] if path.startswith(prefix) else None)
                    super().do_GET()
                def send_response(self, code, message=None):
                    # Only count successful 200/206 transfers; a deleted HLS
                    # segment (404) must not look like healthy playback.
                    name = getattr(self, "_monitor_requested_name", None)
                    if code in (200, 206) and name:
                        now = time.monotonic()
                        with bridge_ref._telemetry_lock:
                            if name == "live.m3u8":
                                bridge_ref._last_playlist_request = now
                            elif name.startswith("part_") and name.endswith(".ts") and "/" not in name:
                                bridge_ref._last_segment_request = now
                                bridge_ref._last_segment_name = name
                    super().send_response(code, message)
                def end_headers(self):
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.send_header('Cache-Control', 'no-store')
                    super().end_headers()
            self.httpd = http.server.ThreadingHTTPServer(('0.0.0.0', 0), Handler)
            LOG.info('HLS servidor temporal iniciado: IP=%s puerto=%d', local_ip, self.httpd.server_port)
            self.httpd.daemon_threads = True
            self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
            self.thread.start()
            segment_seconds, list_size, delete_threshold = HLS_PROFILES[self.profile]
            LOG.info("HLS perfil=%s segmento=%ss lista=%s retención=%s",
                     self.profile, segment_seconds, list_size, delete_threshold)
            # Streaming live input -> H.264 baseline-ish + AAC. Limit resolution/bitrate/CPU.
            args = [
                'ffmpeg', '-hide_banner', '-nostdin', '-loglevel', 'warning',
                '-reconnect', '1', '-reconnect_streamed', '1', '-reconnect_delay_max', '3',
                '-i', self.stream_url,
                '-map', '0:v:0?', '-map', '0:a:0?',
                '-vf', 'scale=1280:720:force_original_aspect_ratio=decrease:force_divisible_by=2',
                '-c:v', 'libx264', '-preset', 'veryfast', '-tune', 'zerolatency',
                '-pix_fmt', 'yuv420p', '-profile:v', 'main', '-level:v', '3.1',
                '-b:v', '2200k', '-maxrate', '2600k', '-bufsize', '5200k',
                '-force_key_frames', f'expr:gte(t,n_forced*{segment_seconds})',
                '-c:a', 'aac', '-b:a', '128k', '-ac', '2', '-ar', '48000',
                '-f', 'hls', '-hls_time', str(segment_seconds), '-hls_list_size', str(list_size),
                '-hls_delete_threshold', str(delete_threshold),
                '-hls_flags', 'delete_segments+omit_endlist+independent_segments',
                '-hls_segment_filename', str(self.stream_dir / 'part_%06d.ts'),
                str(self.stream_dir / 'live.m3u8')
            ]
            self._log_file = open(self.directory / 'ffmpeg.log', 'w+', encoding='utf-8')
            self.process = subprocess.Popen(args, stdin=subprocess.DEVNULL,
                                            stdout=subprocess.DEVNULL,
                                            stderr=self._log_file, start_new_session=True)
            deadline = time.monotonic() + timeout
            playlist = self.stream_dir / 'live.m3u8'
            while time.monotonic() < deadline:
                if self._stopped:
                    raise RuntimeError('Inicio cancelado')
                if self.process.poll() is not None:
                    category, description = ffmpeg_diagnosis(self.error_tail())
                    raise BridgeStartError(category, description)
                if playlist.exists() and list(self.stream_dir.glob('part_*.ts')):
                    return f'http://{local_ip}:{self.httpd.server_port}/{self.token}/live.m3u8'
                time.sleep(0.25)
            category, description = ffmpeg_diagnosis(self.error_tail())
            if category == "ffmpeg":
                description = "FFmpeg no consiguió generar HLS a tiempo; posible fallo de origen o conversión."
            raise BridgeStartError(category, description)
        except Exception:
            self.stop()
            raise

    def error_tail(self):
        try:
            if self._log_file:
                self._log_file.flush()
            content = (self.directory / 'ffmpeg.log').read_text(errors='replace')[-900:]
            # Do not accidentally expose stream credentials in logs.
            content = content.replace(self.stream_url, '[URL oculta]')
            import re
            content = re.sub(r'https?://[^\s\]"\']+', '[URL oculta]', content)
            return content.strip() or 'Sin detalles adicionales de FFmpeg.'
        except OSError:
            return 'Sin registro disponible.'

    def stop(self):
        self._stopped = True
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
        if self._log_file:
            self._log_file.close()
            self._log_file = None
        shutil.rmtree(self.directory, ignore_errors=True)
