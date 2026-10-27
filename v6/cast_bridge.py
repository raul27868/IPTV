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

LOG = logging.getLogger('iptv-video')


class HLSBridge:
    def __init__(self, stream_url: str, cast_ip: str):
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

    @staticmethod
    def lan_ip_for(peer: str) -> str:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect((peer, 8009))
            return sock.getsockname()[0]

    def start(self, timeout: int = 28) -> str:
        if not shutil.which('ffmpeg'):
            raise RuntimeError('No se encuentra FFmpeg: sudo apt install ffmpeg')
        try:
            local_ip = self.lan_ip_for(self.cast_ip)
            # Serve only playlist/segments from this session; avoid directory listings.
            base = self.directory.resolve()
            class Handler(http.server.SimpleHTTPRequestHandler):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, directory=str(base), **kwargs)
                def list_directory(self, path):
                    self.send_error(403)
                    return None
                def log_message(self, format, *args):
                    LOG.debug('HLS HTTP: %s', format % args)
                def end_headers(self):
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.send_header('Cache-Control', 'no-store')
                    super().end_headers()
            self.httpd = http.server.ThreadingHTTPServer(('0.0.0.0', 0), Handler)
            self.httpd.daemon_threads = True
            self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
            self.thread.start()
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
                '-force_key_frames', 'expr:gte(t,n_forced*2)',
                '-c:a', 'aac', '-b:a', '128k', '-ac', '2', '-ar', '48000',
                '-f', 'hls', '-hls_time', '2', '-hls_list_size', '6',
                '-hls_delete_threshold', '3',
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
                    raise RuntimeError('FFmpeg finalizó antes de generar HLS. ' + self.error_tail())
                if playlist.exists() and list(self.stream_dir.glob('part_*.ts')):
                    return f'http://{local_ip}:{self.httpd.server_port}/{self.token}/live.m3u8'
                time.sleep(0.25)
            raise RuntimeError('FFmpeg no produjo segmentos HLS en el tiempo previsto. ' + self.error_tail())
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
