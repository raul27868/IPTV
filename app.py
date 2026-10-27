#!/usr/bin/env python3
"""Explorador M3U y reproductor de vídeo IPTV para Ubuntu."""
from __future__ import annotations

import os
import json
import socket
import tempfile
import uuid
import codecs
import logging
import time
from logging.handlers import RotatingFileHandler
import re
import shutil
import subprocess
import threading
import tkinter as tk
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from urllib.parse import urlparse, urlsplit
from cast_bridge import HLSBridge
from catalog_sqlite import Catalog

APP_VERSION = "14.0"
USER_AGENT = "Mozilla/5.0 IPTV-Video-Explorer/12.0"
LOG_PATH = Path.home() / ".local" / "state" / "iptv-video" / "iptv.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger("iptv-video")
logger.setLevel(logging.INFO)
logger.propagate = False
handler = RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(handler)


def safe_error(exc, url=""):
    # The exception text may embed the request URL; suppress URL-like text and credentials.
    msg = str(exc)
    if url:
        msg = msg.replace(url, "[URL oculta]")
    msg = re.sub(r"https?://[^\s]+", "[URL oculta]", msg, flags=re.I)
    msg = re.sub(r"(?i)(password|username|token|auth|key)=([^&\s]+)", r"\1=[OCULTO]", msg)
    return msg[:600] or "Sin detalle"

MAX_PLAYLIST_BYTES = 512 * 1024 * 1024
DISPLAY_LIMIT = 3000  # Tk Treeview renders a bounded number of matches
ATTRIBUTE_RE = re.compile(r'([\w-]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s,]+))')


@dataclass
class Channel:
    title: str
    url: str
    group: str = "Sin grupo"
    attributes: dict[str, str] = field(default_factory=dict)


def decode_playlist(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def parse_m3u(raw: bytes | str) -> list[Channel]:
    text = decode_playlist(raw) if isinstance(raw, bytes) else raw
    channels: list[Channel] = []
    title: str | None = None
    attrs: dict[str, str] = {}
    group = "Sin grupo"
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#EXTINF:"):
            info = line[len("#EXTINF:"):]
            # The descriptive name begins after the first comma outside quotes.
            in_quote: str | None = None
            split_at = -1
            for idx, ch in enumerate(info):
                if ch in ('"', "'"):
                    if in_quote is None:
                        in_quote = ch
                    elif in_quote == ch:
                        in_quote = None
                elif ch == "," and in_quote is None:
                    split_at = idx
                    break
            metadata = info if split_at < 0 else info[:split_at]
            display = "" if split_at < 0 else info[split_at + 1:].strip()
            attrs = {m.group(1).lower(): next((x for x in m.groups()[1:] if x is not None), "")
                     for m in ATTRIBUTE_RE.finditer(metadata)}
            title = display or attrs.get("tvg-name") or "Sin título"
            group = attrs.get("group-title") or "Sin grupo"
        elif line.startswith("#EXTGRP:"):
            group = line.partition(":")[2].strip() or group
        elif line.startswith("#"):
            continue
        elif urlparse(line).scheme.lower() in ("http", "https", "rtsp", "rtmp", "udp", "rtp", "mms"):
            channels.append(Channel(title or f"Emisión {len(channels)+1}", line, group, dict(attrs)))
            title, attrs, group = None, {}, "Sin grupo"
    return channels


class StreamingM3UParser:
    """M3U incremental: produces entries as soon as each URL line arrives."""
    def __init__(self):
        self.pending: list[str] = []

    def feed_line(self, line: str) -> list[Channel]:
        line = line.strip()
        if not line:
            return []
        if line.startswith("#EXTINF:"):
            self.pending = [line]
        elif line.startswith("#EXTGRP:"):
            self.pending.append(line)
        elif not line.startswith("#"):
            candidate = parse_m3u("\n".join(self.pending + [line]))
            self.pending = []
            return candidate
        return []


class VideoIPTVApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(f"IPTV Vídeo · Explorador M3U · v{APP_VERSION}")
        root.geometry("1080x690")
        root.minsize(760, 480)
        self.catalog = Catalog()
        self.channels: list[Channel] = []  # Compatibility; entries live in SQLite
        self.last_render = 0.0
        self.visible: list[int] = []
        self.player: subprocess.Popen | None = None
        self.mpv_socket: str | None = None
        self.playing_channel: Channel | None = None
        self.cast_devices = {}
        self.cast_device = None
        self.cast_browser = None
        self.cast_busy = False
        self.bridge = None
        self.cast_session = 0
        self.cast_mode = tk.StringVar(value="Directo (menos CPU)")
        self.cast_request_number = 0
        self.cast_var = tk.StringVar(value="Local (mpv)")
        self.request_number = 0
        self.loading = False
        self.received_bytes = 0
        self.last_diagnostic = "Sin eventos todavía."
        self.load_source = ""
        self.file_size = None
        self._filter_after = None
        self.url_var = tk.StringVar()
        self.direct_url_var = tk.StringVar()
        self.search_var = tk.StringVar()
        self.group_var = tk.StringVar(value="Todos los grupos")
        self.status_var = tk.StringVar(value="Introduce el enlace de la lista M3U o abre un archivo local.")
        self.playing_var = tk.StringVar(value="Sin reproducción")
        self._build()
        self.group_box["values"] = ["Todos los grupos"] + self.catalog.groups()
        self.render()
        root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build(self):
        shell = ttk.Frame(self.root, padding=12)
        shell.pack(fill="both", expand=True)
        ttk.Label(shell, text="URL de la lista M3U / M3U Plus").pack(anchor="w")
        r = ttk.Frame(shell)
        r.pack(fill="x", pady=(4, 8))
        entry = ttk.Entry(r, textvariable=self.url_var)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _: self.load_remote())
        ttk.Button(r, text="Cargar URL", command=self.load_remote).pack(side="left", padx=(8, 0))
        ttk.Button(r, text="Cancelar carga", command=self.cancel_load).pack(side="left", padx=(8, 0))
        ttk.Button(r, text="Abrir archivo…", command=self.load_local).pack(side="left", padx=(8, 0))
        ttk.Button(r, text="Diagnóstico", command=self.show_diagnostic).pack(side="left", padx=(8, 0))

        direct = ttk.LabelFrame(shell, text="Reproducir enlace directo (sin cargar lista)", padding=7)
        direct.pack(fill="x", pady=(0, 5))
        direct_row = ttk.Frame(direct)
        direct_row.pack(fill="x")
        direct_entry = ttk.Entry(direct_row, textvariable=self.direct_url_var)
        direct_entry.pack(side="left", fill="x", expand=True)
        direct_entry.bind("<Return>", lambda _: self.play_direct_url())
        ttk.Button(direct_row, text="▶ Reproducir URL", command=self.play_direct_url).pack(side="left", padx=(8, 0))

        filters = ttk.Frame(shell)
        filters.pack(fill="x", pady=(8, 8))
        ttk.Label(filters, text="Buscar:").pack(side="left")
        ttk.Entry(filters, textvariable=self.search_var, width=38).pack(side="left", padx=(6, 16), fill="x", expand=True)
        ttk.Label(filters, text="Grupo:").pack(side="left")
        self.group_box = ttk.Combobox(filters, textvariable=self.group_var, state="readonly", width=25)
        self.group_box.pack(side="left", padx=(6, 0))
        self.group_box["values"] = ["Todos los grupos"]
        self.group_box.bind("<<ComboboxSelected>>", lambda _: self.render())
        self.search_var.trace_add("write", lambda *_: self.schedule_render())

        table_frame = ttk.Frame(shell)
        table_frame.pack(fill="both", expand=True)
        self.table = ttk.Treeview(table_frame, columns=("title", "group", "id"), show="headings", selectmode="browse")
        self.table.heading("title", text="Canal / evento")
        self.table.heading("group", text="Grupo")
        self.table.heading("id", text="tvg-id")
        self.table.column("title", width=540, minwidth=200)
        self.table.column("group", width=160, minwidth=90)
        self.table.column("id", width=150, minwidth=80)
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.table.bind("<<TreeviewSelect>>", lambda _: self.show_details())
        self.table.bind("<Double-1>", lambda _: self.play_selected())

        details_frame = ttk.LabelFrame(shell, text="Información del elemento seleccionado", padding=7)
        details_frame.pack(fill="x", pady=(10, 6))
        self.details = tk.Text(details_frame, height=7, wrap="word", state="disabled")
        self.details.pack(fill="x")
        ttk.Button(details_frame, text="Copiar enlace de emisión", command=self.copy_selected_url).pack(anchor="e", pady=(3, 0))

        actions = ttk.Frame(shell)
        actions.pack(fill="x", pady=(2, 6))
        ttk.Button(actions, text="▶ Ver vídeo", command=self.play_selected).pack(side="left")
        ttk.Button(actions, text="■ Detener", command=self.stop).pack(side="left", padx=7)
        ttk.Label(actions, text="Procesador:").pack(side="left", padx=(14, 4))
        self.cast_box = ttk.Combobox(actions, textvariable=self.cast_var, state="readonly", width=24)
        self.cast_box["values"] = ["Local (mpv)"]
        self.cast_box.pack(side="left")
        ttk.Button(actions, text="Buscar dispositivos", command=self.discover_cast).pack(side="left", padx=(6, 0))
        ttk.Label(actions, text="Modo:").pack(side="left", padx=(10, 3))
        ttk.Combobox(actions, textvariable=self.cast_mode, state="readonly", width=22,
                     values=["Directo (menos CPU)", "Compatible (FFmpeg/HLS)"]).pack(side="left")
        ttk.Label(actions, textvariable=self.playing_var).pack(side="left", padx=16)
        footer = ttk.Frame(shell)
        footer.pack(fill="x", pady=(4, 0))
        ttk.Label(footer, textvariable=self.status_var, anchor="w").pack(side="left", fill="x", expand=True)
        ttk.Label(footer, text=f"IPTV Vídeo  v{APP_VERSION}", foreground="#777777").pack(side="right", padx=(12, 0))

    def selected_channel(self) -> Channel | None:
        selected = self.table.selection()
        if not selected:
            return None
        try:
            record = self.catalog.get(int(selected[0]))
            return Channel(record[0], record[1], record[2], record[3]) if record else None
        except (ValueError, TypeError):
            return None

    def copy_selected_url(self):
        item = self.selected_channel()
        if item is not None:
            self.root.clipboard_clear()
            self.root.clipboard_append(item.url)
            self.status_var.set("Enlace copiado al portapapeles (puede contener credenciales).")

    def show_details(self):
        item = self.selected_channel()
        if item is None:
            s = ""
        else:
            # The user explicitly wants the stream link visible. Never send it to logs.
            # Be aware that the link may contain IPTV credentials.
            parsed = urlparse(item.url)
            host = parsed.hostname or "Desconocido"
            lines = [f"Título: {item.title}", f"Grupo: {item.group}",
                     f"Servidor: {host}", f"Protocolo: {parsed.scheme}",
                     f"Enlace de emisión: {item.url}"]
            lines += [f"{key}: {value}" for key, value in item.attributes.items() if key not in ("group-title",)]
            s = "\n".join(lines)
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", s)
        self.details.configure(state="disabled")

    def schedule_render(self):
        if self._filter_after is not None:
            self.root.after_cancel(self._filter_after)
        self._filter_after = self.root.after(250, self.render)

    def render(self):
        self._filter_after = None
        query = self.search_var.get().strip()
        group = self.group_var.get()
        try:
            total, rows = self.catalog.search(query, group, limit=DISPLAY_LIMIT)
        except Exception as exc:
            logger.warning("Error de búsqueda en catálogo: %s", type(exc).__name__)
            self.status_var.set("Error de búsqueda: consulta no válida")
            return
        self.visible = [row[0] for row in rows]
        self.match_count = total
        self.table.delete(*self.table.get_children())
        for ident, title, group_name, tvg_id in rows:
            self.table.insert("", "end", iid=str(ident), values=(title, group_name, tvg_id or ""))
        self.last_render = time.monotonic()
        self._update_status()
        self.show_details()

    def _update_status(self):
        suffix = " · leyendo…" if self.loading else ""
        count = getattr(self, "match_count", 0)
        shown = len(self.visible)
        extra = f" · mostrando {shown} de {count} coincidencias" if count > shown else ""
        progress = f" / {self.file_size / 1048576:.1f} MB ({100*self.received_bytes/self.file_size:.0f}%)" if self.file_size else ""
        self.status_var.set(f"{count} coincidencias · {self.catalog.count()} canales · "
                            f"{self.received_bytes / 1048576:.2f} MB{progress}{suffix}{extra}")

    def _append_batch(self, items: list[Channel], byte_count: int, request_id: int):
        if request_id != self.request_number:
            return
        try:
            self.catalog.add(items)
        except Exception as exc:
            logger.exception("Error guardando bloque de canales en SQLite")
            self._stream_error(request_id, f"Escritura SQLite: {type(exc).__name__}: {exc}")
            return
        self.received_bytes = byte_count
        # No recorrer la colección completa ni redibujar 3000 filas por cada bloque.
        if time.monotonic() - self.last_render >= 0.75:
            self.render()
        else:
            self._update_status()

    def _finish_load(self, request_id: int):
        if request_id != self.request_number:
            return
        self.loading = False
        self.group_box["values"] = ["Todos los grupos"] + self.catalog.groups()
        self.render()
        n = self.catalog.count()
        if not n:
            self._load_error("Lista vacía", "No se encontraron entradas M3U en los datos recibidos.")
        else:
            logger.info("Descarga finalizada: canales=%d bytes=%d", n, self.received_bytes)

    def cancel_load(self):
        if self.loading:
            self.request_number += 1
            self.loading = False
            self._update_status()
            logger.info("Carga cancelada por el usuario. Canales conservados: %d", self.catalog.count())

    def set_channels(self, items: list[Channel], source: str):
        self.catalog.reset()
        self.catalog.add(items)
        self.group_box["values"] = ["Todos los grupos"] + self.catalog.groups()
        self.group_var.set("Todos los grupos")
        self.search_var.set("")
        self.render()
        if not items:
            messagebox.showwarning("Lista vacía", "No se encontraron entradas compatibles en la lista.")
        else:
            self.status_var.set(f"Cargadas {len(items)} entradas desde {source}")

    def _begin_load(self, source, total_size=None):
        # A new load invalidates any pending worker updates, but does not stop playback.
        self.request_number += 1
        request_id = self.request_number
        self.catalog.reset()
        self.channels = []
        self.visible = []
        self.received_bytes = 0
        self.file_size = total_size
        self.load_source = source
        self.loading = True
        self.table.delete(*self.table.get_children())
        self.group_var.set("Todos los grupos")
        self.group_box["values"] = ["Todos los grupos"]
        self.search_var.set("")
        self.match_count = 0
        self._update_status()
        return request_id

    def load_local(self):
        path = filedialog.askopenfilename(
            title="Seleccionar lista M3U",
            filetypes=[("Listas M3U / ejemplo TS", "*.m3u *.m3u8 *.ts *.txt"), ("Todos", "*")])
        if not path:
            return
        try:
            size = Path(path).stat().st_size
            if size > MAX_PLAYLIST_BYTES:
                raise ValueError(f"El archivo supera el límite de {MAX_PLAYLIST_BYTES // 1048576} MB")
        except (OSError, ValueError) as exc:
            self._load_error("Archivo local", safe_error(exc))
            return
        request_id = self._begin_load(Path(path).name, size)
        logger.info("Lectura local incremental iniciada: tamaño=%d bytes", size)

        def work():
            stage, total, parsed_count = "Lectura local", 0, 0
            start_time = time.monotonic()
            try:
                decoder = codecs.getincrementaldecoder("utf-8-sig")("replace")
                parser = StreamingM3UParser()
                remainder = ""
                batch = []
                last_update = time.monotonic()
                with open(path, "rb") as infile:
                    while True:
                        if request_id != self.request_number:
                            return
                        chunk = infile.read(65536)
                        if not chunk:
                            break
                        total += len(chunk)
                        remainder += decoder.decode(chunk)
                        lines = remainder.split("\n")
                        remainder = lines.pop()
                        for line in lines:
                            found = parser.feed_line(line.rstrip("\r"))
                            batch.extend(found)
                            parsed_count += len(found)
                        now = time.monotonic()
                        if len(batch) >= 250 or now - last_update >= 0.25:
                            payload, batch = batch, []
                            self.root.after(0, lambda b=payload, n=total: self._append_batch(b, n, request_id))
                            last_update = now
                remainder += decoder.decode(b"", final=True)
                for line in remainder.splitlines():
                    found = parser.feed_line(line)
                    batch.extend(found)
                    parsed_count += len(found)
                self.root.after(0, lambda b=batch, n=total: self._append_batch(b, n, request_id))
                self.root.after(0, lambda: self._finish_load(request_id))
                logger.info("Lectura local finalizada: bytes=%d canales=%d duración=%.1fs", total, parsed_count, time.monotonic()-start_time)
            except Exception as exc:
                diagnostic = (f"Etapa: {stage}\nError: {type(exc).__name__}\n"
                              f"Motivo: {safe_error(exc)}\nBytes leídos: {total}\n"
                              f"Canales detectados: {parsed_count}")
                logger.error("Lectura local fallida: %s", diagnostic.replace("\n", " | "))
                try:
                    self.root.after(0, lambda: self._stream_error(request_id, diagnostic))
                except RuntimeError:
                    pass
        threading.Thread(target=work, daemon=True).start()

    def show_diagnostic(self):
        win = tk.Toplevel(self.root)
        win.title("Diagnóstico de carga")
        win.geometry("780x400")
        outer = ttk.Frame(win, padding=12)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text=f"Archivo de registro: {LOG_PATH}").pack(anchor="w")
        txt = tk.Text(outer, wrap="word")
        txt.pack(fill="both", expand=True, pady=8)
        try:
            txt.insert("1.0", LOG_PATH.read_text(encoding="utf-8")[-15000:])
        except OSError:
            txt.insert("1.0", self.last_diagnostic)
        txt.configure(state="disabled")
        ttk.Button(outer, text="Cerrar", command=win.destroy).pack(anchor="e")

    def load_remote(self):
        url = self.url_var.get().strip()
        try:
            parsed = urlsplit(url)
            if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
                raise ValueError("Falta el protocolo HTTP(S) o un servidor válido")
            port = parsed.port
        except ValueError as exc:
            self._load_error("Validación de URL", safe_error(exc, url))
            return
        request_id = self._begin_load("URL")
        host = parsed.hostname or "desconocido"
        logger.info("Descarga incremental solicitada: servidor=%s puerto=%s protocolo=%s", host, port or "predeterminado", parsed.scheme)

        def work():
            started = time.monotonic()
            stage = "Solicitud HTTP"
            total = 0
            parsed_count = 0
            batch = []
            last_update = time.monotonic()
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
                with urllib.request.urlopen(req, timeout=30) as response:
                    try:
                        length = int(response.headers.get("Content-Length", ""))
                        if length > 0:
                            self.root.after(0, lambda n=length: self._set_remote_size(request_id, n))
                    except (ValueError, TypeError):
                        pass
                    stage = "Recepción incremental"
                    ctype = response.headers.get("Content-Type", "desconocido")
                    logger.info("Respuesta HTTP %s tipo=%s", response.status, ctype)
                    decoder = codecs.getincrementaldecoder("utf-8-sig")("replace")
                    parser = StreamingM3UParser()
                    remainder = ""
                    while True:
                        if request_id != self.request_number:
                            return
                        chunk = response.read(65536)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > MAX_PLAYLIST_BYTES:
                            raise ValueError("La lista supera el límite de 200 MB")
                        remainder += decoder.decode(chunk)
                        lines = remainder.split("\n")
                        remainder = lines.pop()
                        for line in lines:
                            found = parser.feed_line(line.rstrip("\r"))
                            batch.extend(found)
                            parsed_count += len(found)
                        now = time.monotonic()
                        if len(batch) >= 100 or now - last_update >= 0.25:
                            payload = batch
                            batch = []
                            self.root.after(0, lambda b=payload, n=total: self._append_batch(b, n, request_id))
                            last_update = now
                    remainder += decoder.decode(b"", final=True)
                    for line in remainder.splitlines():
                        found = parser.feed_line(line)
                        batch.extend(found)
                        parsed_count += len(found)
                    self.root.after(0, lambda b=batch, n=total: self._append_batch(b, n, request_id))
                    self.root.after(0, lambda: self._finish_load(request_id))
                    logger.info("Recibidos %d bytes y %d canales en %.1fs", total, parsed_count, time.monotonic()-started)
            except Exception as exc:
                detail = safe_error(exc, url)
                if isinstance(exc, urllib.error.HTTPError):
                    detail = f"HTTP {exc.code}: {safe_error(Exception(str(exc.reason)), url)}"
                diagnostic = (f"Etapa: {stage}\nError: {type(exc).__name__}\n"
                              f"Motivo: {detail}\nServidor: {host}\n"
                              f"Datos recibidos: {total} bytes\nCanales analizados: {parsed_count}\n"
                              f"Duración: {time.monotonic()-started:.1f}s")
                logger.error("Carga fallida: %s", diagnostic.replace("\n", " | "))
                try:
                    self.root.after(0, lambda: self._stream_error(request_id, diagnostic))
                except RuntimeError:
                    pass
        threading.Thread(target=work, daemon=True).start()

    def _set_remote_size(self, request_id, size):
        if request_id == self.request_number:
            self.file_size = size
            self._update_status()

    def _stream_error(self, request_id, diagnostic):
        if request_id == self.request_number:
            self.loading = False
            self._load_error("Descarga parcial", diagnostic)

    def _load_error(self, kind: str, diagnostic: str):
        self.last_diagnostic = diagnostic
        self.status_var.set(f"Error de carga: {kind}")
        logger.error("Diagnóstico: %s", diagnostic.replace("\n", " | "))
        messagebox.showerror("Error al cargar lista", diagnostic + "\n\nUsa el botón Diagnóstico para ver el registro.")

    def play_direct_url(self):
        url = self.direct_url_var.get().strip()
        parts = urlsplit(url)
        if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
            messagebox.showwarning("Enlace no válido", "Introduce una URL HTTP o HTTPS directa al vídeo.")
            return
        # Treat as an ordinary Channel; use exactly the same player/processor path.
        item = Channel(title="Enlace directo", url=url, group="Directo")
        logger.info("Reproducción URL directa solicitada: servidor=%s modo=%s",
                    parts.hostname, self.cast_mode.get() if self.cast_var.get() != "Local (mpv)" else "mpv")
        self.play_item(item)

    def play_selected(self):
        item = self.selected_channel()
        if item is None:
            messagebox.showinfo("Selecciona un elemento", "Selecciona una entrada de la tabla.")
            return
        self.play_item(item)

    def _mpv_command(self, command: list, *, timeout: float = 1.5) -> bool:
        """Send a command to the existing mpv process, preserving its window."""
        path = self.mpv_socket
        if not path or not self.player or self.player.poll() is not None:
            return False
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
                conn.settimeout(timeout)
                conn.connect(path)
                conn.sendall((json.dumps({"command": command}) + "\n").encode("utf-8"))
                response = b""
                while b"\n" not in response and len(response) < 65536:
                    part = conn.recv(4096)
                    if not part:
                        break
                    response += part
            result = json.loads(response.split(b"\n", 1)[0])
            if result.get("error") != "success":
                logger.warning("mpv IPC rechazó el comando: %s", result.get("error"))
                return False
            return True
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("mpv IPC no disponible: %s", type(exc).__name__)
            return False

    def play_item(self, item):
        if self.cast_var.get() != "Local (mpv)":
            self.play_cast(item)
            return
        if not shutil.which("mpv"):
            messagebox.showerror("Falta mpv", "Instala el reproductor con: sudo apt install mpv")
            return

        # A running mpv is kept alive: changing its playlist entry does not
        # change the native window's geometry or screen position.
        if self.player is not None and self.player.poll() is None:
            if self._mpv_command(["loadfile", item.url, "replace"]):
                self.playing_channel = item
                self.playing_var.set(f"▶ {item.title}")
                self.status_var.set("Canal cambiado en la misma ventana mpv.")
                logger.info("mpv IPC: cambio de canal sin recrear ventana")
                return
            logger.warning("mpv IPC falló: se reiniciará únicamente este reproductor")

        self.stop()
        try:
            # Restrict the IPC socket to the current user's private temp folder.
            directory = Path(tempfile.mkdtemp(prefix="iptv-mpv-"))
            os.chmod(directory, 0o700)
            self.mpv_socket = str(directory / "control.sock")
            self.player = subprocess.Popen(
                ["mpv", "--no-config", "--force-window=yes", "--idle=yes",
                 "--title=IPTV Vídeo", "--cache=yes", "--demuxer-readahead-secs=6",
                 f"--input-ipc-server={self.mpv_socket}", "--", item.url],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True)
            self.playing_channel = item
            self.playing_var.set(f"▶ {item.title}")
            self.status_var.set("Vídeo en mpv. Al cambiar de canal se mantiene la ventana.")
            process = self.player
            threading.Thread(target=self._watch_player, args=(process,), daemon=True).start()
        except OSError as exc:
            self._cleanup_mpv_socket()
            logger.error("No se pudo iniciar mpv: %s", type(exc).__name__)
            messagebox.showerror("Error", "No se pudo iniciar mpv.")

    def _cleanup_mpv_socket(self):
        path = self.mpv_socket
        self.mpv_socket = None
        if path:
            try:
                Path(path).unlink(missing_ok=True)
                Path(path).parent.rmdir()
            except OSError:
                pass

    def _watch_player(self, process: subprocess.Popen):
        rc = process.wait()
        logger.info("Reproductor finalizado con código %s", rc)
        def report():
            if self.player is process:
                self.player = None
                self._cleanup_mpv_socket()
                self.playing_channel = None
                self.playing_var.set("Sin reproducción")
                self.status_var.set("Emisión finalizada o no accesible." if rc else "Reproducción finalizada.")
        try:
            self.root.after(0, report)
        except RuntimeError:
            pass

    def stop(self):
        self.cast_session += 1
        bridge = self.bridge
        self.bridge = None
        if bridge is not None:
            threading.Thread(target=bridge.stop, daemon=True).start()
        if self.cast_device is not None:
            cast = self.cast_device
            self.cast_device = None
            def stop_cast():
                try:
                    cast.media_controller.stop()
                except Exception as exc:
                    logger.warning("No se pudo detener Cast: %s", type(exc).__name__)
                finally:
                    try:
                        cast.disconnect()
                    except Exception as exc:
                        logger.debug("Desconexión Google Cast: %s", type(exc).__name__)
            threading.Thread(target=stop_cast, daemon=True).start()
        proc = self.player
        self.player = None
        self.playing_channel = None
        self.playing_var.set("Sin reproducción")
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=1.5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
        self._cleanup_mpv_socket()


    def discover_cast(self):
        """Discover Google Cast devices and transfer browser ownership to Tk safely.

        The discovery thread must not invalidate the browser before the Tk
        callback stores it; CastInfo may still require its live Zeroconf.
        """
        if self.cast_busy:
            self.status_var.set("Ya hay una búsqueda de dispositivos en curso.")
            return
        self.cast_busy = True
        self.cast_request_number += 1
        generation = self.cast_request_number
        self.status_var.set("Buscando dispositivos Google Cast en la red local…")

        def worker():
            browser = None
            transferred = False
            try:
                import pychromecast
                devices, browser = pychromecast.get_chromecasts(timeout=8)
                found = {}
                for cast in devices:
                    info = cast.cast_info
                    label = f"{info.friendly_name or 'Dispositivo Cast'} [{str(cast.uuid)[:8]}]"
                    found[label] = info
                    try:
                        cast.disconnect()
                    except Exception:
                        pass

                # Bind the live browser into the callback argument, rather than
                # capturing a mutable nonlocal variable subsequently set to None.
                def update(discovered_browser=browser, discovered=found):
                    try:
                        if generation != self.cast_request_number:
                            self._close_browser_later(discovered_browser, delay=0)
                            return
                        self.stop()
                        old_browser = self.cast_browser
                        self.cast_browser = discovered_browser
                        self.cast_devices = discovered
                        names = ["Local (mpv)"] + sorted(discovered)
                        self.cast_box["values"] = names
                        if self.cast_var.get() not in names:
                            self.cast_var.set("Local (mpv)")
                        self.status_var.set(
                            f"Encontrados {len(discovered)} dispositivos Google Cast." if discovered
                            else "Sin dispositivos Google Cast. Comprueba Wi-Fi, mDNS y aislamiento de red.")
                        logger.info("Cast descubrimiento activo: dispositivos=%d zeroconf=%s",
                                    len(discovered), bool(getattr(discovered_browser, 'zc', None)))
                        if old_browser is not None and old_browser is not discovered_browser:
                            threading.Thread(target=self._close_browser_later,
                                             args=(old_browser,), daemon=True).start()
                    finally:
                        self.cast_busy = False

                self.root.after(0, update)
                transferred = True
            except ImportError:
                self.root.after(0, lambda: messagebox.showerror(
                    "Falta Google Cast", "Instala la dependencia opcional:\npython -m pip install PyChromecast\n\nUsa el entorno virtual activo."))
            except Exception as exc:
                detail = safe_error(exc)
                logger.warning("Descubrimiento Google Cast: %s", detail)
                self.root.after(0, lambda d=detail: self.status_var.set(f"Error buscando dispositivos: {d}"))
            finally:
                if browser is not None and not transferred:
                    try:
                        browser.stop_discovery()
                    except Exception:
                        pass
                if not transferred:
                    try:
                        self.root.after(0, lambda: setattr(self, "cast_busy", False))
                    except RuntimeError:
                        pass
        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def _close_browser_later(browser, delay=3):
        time.sleep(delay)
        try:
            browser.stop_discovery()
        except Exception as exc:
            logger.debug("Cierre descubrimiento Google Cast: %s", type(exc).__name__)

    @staticmethod
    def cast_mime(url):
        """Use a content-type hint; the receiver still decides actual support."""
        path = urlsplit(url).path.lower()
        if path.endswith(".m3u8"):
            return "application/vnd.apple.mpegurl"
        if path.endswith((".ts", ".m2ts")):
            return "video/mp2t"
        if path.endswith(".mp4"):
            return "video/mp4"
        if path.endswith(".mpd"):
            return "application/dash+xml"
        # Unknown endpoint: do not claim MPEG-TS without examining the stream.
        return None

    def play_cast(self, item):
        name = self.cast_var.get()
        cast_info = self.cast_devices.get(name)
        if cast_info is None:
            messagebox.showwarning("Procesador no disponible", "Vuelve a buscar el dispositivo o selecciona Local.")
            return
        if urlsplit(item.url).scheme not in ("http", "https"):
            messagebox.showwarning("Formato no compatible", "Cast requiere una URL HTTP(S).")
            return
        requested_direct = self.cast_mode.get() == "Directo (menos CPU)"
        direct_mime = self.cast_mime(item.url)
        # Cast Default Media Receiver does not reliably handle raw MPEG-TS.
        # Also avoid pretending an unknown /live/ URL is video/mp2t.
        compatibility = not requested_direct or direct_mime in (None, "video/mp2t")
        if requested_direct and compatibility:
            self.status_var.set("MPEG-TS o formato desconocido: usando conversión HLS para Google TV.")
            logger.info("Google Cast selección automática de HLS: tipo original=%s", direct_mime or "desconocido")
        if compatibility and not shutil.which('ffmpeg'):
            messagebox.showerror("Falta FFmpeg", "Instala el conversor: sudo apt install ffmpeg")
            return
        self.stop()
        session = self.cast_session
        self.playing_channel = item
        self.playing_var.set(f"⇥ {item.title} → {name}")
        self.status_var.set("Preparando emisión HLS compatible…" if compatibility else
                            "Enviando URL directamente al televisor…")

        def worker():
            bridge = None
            cast = None
            try:
                import pychromecast
                browser = self.cast_browser
                if browser is None:
                    raise RuntimeError("La sesión de descubrimiento Cast no está activa: busca dispositivos de nuevo.")
                # A fresh Chromecast object / worker per attempt. No restarted threads.
                cast = pychromecast.get_chromecast_from_cast_info(
                    cast_info, zconf=browser.zc, tries=2, timeout=10, retry_wait=2)
                self.cast_device = cast
                logger.info("Google Cast conexión iniciada: dispositivo=%s host=%s",
                            name, cast_info.host)
                cast.wait(timeout=15)
                logger.info("Google Cast conectado: dispositivo=%s", name)
                logger.info("Google Cast receptor: app=%s estado=%s", cast.status.app_id, cast.status.display_name)
                media_url, mime = item.url, direct_mime
                if compatibility:
                    host = getattr(cast, 'host', None) or getattr(cast.cast_info, 'host', None)
                    if not host:
                        raise RuntimeError('No se pudo identificar la dirección IP del televisor.')
                    bridge = HLSBridge(item.url, host)
                    # Avoid accumulating stale bridge sessions after switching channels.
                    if session != self.cast_session:
                        return
                    media_url = bridge.start()
                    mime = 'application/vnd.apple.mpegurl'
                    if session != self.cast_session:
                        return
                    self.bridge = bridge
                if session != self.cast_session:
                    return
                cast.media_controller.play_media(media_url, mime, title=item.title,
                                                 stream_type="LIVE")
                logger.info("Cast LOAD solicitado: dispositivo=%s modo=%s tipo=%s servidor=%s", name,
                            'HLS compatible' if compatibility else 'directo', mime,
                            urlsplit(media_url).hostname)
                # play_media queues a LOAD command; it does not prove playback succeeded.
                # Inspect the receiver state instead of claiming delivery.
                controller = cast.media_controller
                last_state = None
                last_reason = None
                outcome = None
                start = time.monotonic()
                while time.monotonic() - start < 22:
                    if session != self.cast_session:
                        return
                    status = controller.status
                    state = status.player_state or "UNKNOWN"
                    reason = status.idle_reason or ""
                    if (state, reason) != (last_state, last_reason):
                        logger.info("Google Cast estado: dispositivo=%s estado=%s motivo=%s app=%s",
                                    name, state, reason or "(ninguno)", cast.status.display_name)
                        last_state, last_reason = state, reason
                        def update(st=state, why=reason):
                            if session == self.cast_session:
                                self.status_var.set(f"Google TV: {st}" + (f" ({why})" if why else ""))
                        self.root.after(0, update)
                    if state == "PLAYING":
                        outcome = "PLAYING"
                        break
                    if state == "IDLE" and reason in ("ERROR", "LOAD_FAILED", "CANCELLED"):
                        outcome = f"IDLE/{reason}"
                        break
                    time.sleep(0.5)
                if session == self.cast_session:
                    status = controller.status
                    result = outcome or f"sin confirmar (estado {status.player_state}, motivo {status.idle_reason})"
                    logger.info("Google Cast resultado tras 22s: %s", result)
                    if result != "PLAYING":
                        logger.warning("Cast no confirma vídeo: icono Cast en TV solo confirma apertura del receptor. "
                                       "Comprueba accesibilidad del URL desde TV, MIME/códecs, HTTP/HTTPS y, "
                                       "en modo HLS, acceso al servidor temporal en Ubuntu.")
                    self.root.after(0, lambda r=result: self.status_var.set(
                        "Google TV: " + r + (". Revisa Diagnóstico." if r != "PLAYING" else " — reproduciendo.")))
            except Exception as exc:
                detail = safe_error(exc, item.url)
                logger.warning("Error Google Cast modo=%s dispositivo=%s: %s",
                               'compatible' if compatibility else 'directo', name, detail)
                err_type = type(exc).__name__
                def fail():
                    if session == self.cast_session:
                        if self.cast_device is cast:
                            self.cast_device = None
                        self.playing_channel = None
                        self.playing_var.set("Sin reproducción")
                        self.status_var.set("Error enviando vídeo a Google TV.")
                        messagebox.showerror("Error Google Cast", f"{err_type}: {detail}")
                try:
                    self.root.after(0, fail)
                except RuntimeError:
                    pass
            finally:
                if cast is not None and (session != self.cast_session or self.cast_device is not cast):
                    try:
                        cast.disconnect()
                    except Exception:
                        pass
                if bridge is not None and (session != self.cast_session or self.bridge is not bridge):
                    bridge.stop()
        threading.Thread(target=worker, daemon=True).start()

    def on_close(self):
        self.request_number += 1
        self.cast_request_number += 1
        self.stop()
        browser = self.cast_browser
        self.cast_browser = None
        if browser is not None:
            threading.Thread(target=self._close_browser_later, args=(browser,), daemon=True).start()
        self.root.destroy()
        self.catalog.close()


def main():
    root = tk.Tk()
    try:
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
    except tk.TclError:
        pass
    VideoIPTVApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
