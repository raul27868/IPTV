#!/usr/bin/env python3
"""Explorador M3U y reproductor de vídeo IPTV para Ubuntu."""
from __future__ import annotations

import os
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

USER_AGENT = "Mozilla/5.0 IPTV-Video-Explorer/2.0"
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
        root.title("IPTV Vídeo · Explorador M3U")
        root.geometry("1080x690")
        root.minsize(760, 480)
        self.channels: list[Channel] = []
        self.visible: list[int] = []
        self.player: subprocess.Popen | None = None
        self.playing_channel: Channel | None = None
        self.request_number = 0
        self.loading = False
        self.received_bytes = 0
        self.last_diagnostic = "Sin eventos todavía."
        self.load_source = ""
        self.file_size = None
        self._filter_after = None
        self.url_var = tk.StringVar()
        self.search_var = tk.StringVar()
        self.group_var = tk.StringVar(value="Todos los grupos")
        self.status_var = tk.StringVar(value="Introduce el enlace de la lista M3U o abre un archivo local.")
        self.playing_var = tk.StringVar(value="Sin reproducción")
        self._build()
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
        self.details = tk.Text(details_frame, height=5, wrap="word", state="disabled")
        self.details.pack(fill="x")

        actions = ttk.Frame(shell)
        actions.pack(fill="x", pady=(2, 6))
        ttk.Button(actions, text="▶ Ver vídeo", command=self.play_selected).pack(side="left")
        ttk.Button(actions, text="■ Detener", command=self.stop).pack(side="left", padx=7)
        ttk.Label(actions, textvariable=self.playing_var).pack(side="left", padx=16)
        ttk.Label(shell, textvariable=self.status_var, anchor="w").pack(fill="x", pady=(4, 0))

    def selected_channel(self) -> Channel | None:
        selected = self.table.selection()
        if not selected:
            return None
        try:
            return self.channels[int(selected[0])]
        except (ValueError, IndexError):
            return None

    def show_details(self):
        item = self.selected_channel()
        if item is None:
            s = ""
        else:
            # URLs may include credentials. Show host/stream type, but not full URL.
            parsed = urlparse(item.url)
            host = parsed.hostname or "Desconocido"
            lines = [f"Título: {item.title}", f"Grupo: {item.group}",
                     f"Servidor: {host}", f"Protocolo: {parsed.scheme}"]
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
        query = self.search_var.get().casefold().strip()
        group = self.group_var.get()
        self.table.delete(*self.table.get_children())
        self.visible = []
        for i, ch in enumerate(self.channels):
            if group != "Todos los grupos" and ch.group != group:
                continue
            if query and query not in (ch.title + " " + ch.group + " " + " ".join(ch.attributes.values())).casefold():
                continue
            self.visible.append(i)
            if len(self.visible) <= DISPLAY_LIMIT:
                self.table.insert("", "end", iid=str(i), values=(ch.title, ch.group, ch.attributes.get("tvg-id", "")))
        if self.channels:
            self._update_status()
        self.show_details()

    def _update_status(self):
        suffix = " · leyendo…" if self.loading else ""
        count = len(self.visible)
        shown = min(count, DISPLAY_LIMIT)
        extra = f" · mostrando {shown} de {count} coincidencias (afina la búsqueda)" if count > DISPLAY_LIMIT else ""
        progress = f" / {self.file_size / 1048576:.1f} MB ({100*self.received_bytes/self.file_size:.0f}%)" if self.file_size else ""
        self.status_var.set(f"{count} coincidencias · {len(self.channels)} canales · "
                            f"{self.received_bytes / 1048576:.2f} MB{progress}{suffix}{extra}")

    def _append_batch(self, items: list[Channel], byte_count: int, request_id: int):
        if request_id != self.request_number:
            return
        start = len(self.channels)
        self.channels.extend(items)
        self.received_bytes = byte_count
        known_groups = set(self.group_box["values"])
        for i, ch in enumerate(items, start):
            if ch.group not in known_groups:
                known_groups.add(ch.group)
            group = self.group_var.get()
            query = self.search_var.get().casefold().strip()
            if group != "Todos los grupos" and ch.group != group:
                continue
            if query and query not in (ch.title + " " + ch.group + " " + " ".join(ch.attributes.values())).casefold():
                continue
            self.visible.append(i)
            if len(self.visible) <= DISPLAY_LIMIT:
                self.table.insert("", "end", iid=str(i), values=(ch.title, ch.group, ch.attributes.get("tvg-id", "")))
        self.group_box["values"] = ["Todos los grupos"] + sorted(known_groups - {"Todos los grupos"}, key=str.casefold)
        self._update_status()

    def _finish_load(self, request_id: int):
        if request_id != self.request_number:
            return
        self.loading = False
        self._update_status()
        if not self.channels:
            self._load_error("Lista vacía", "No se encontraron entradas M3U en los datos recibidos.")
        else:
            logger.info("Descarga finalizada: canales=%d bytes=%d", len(self.channels), self.received_bytes)

    def cancel_load(self):
        if self.loading:
            self.request_number += 1
            self.loading = False
            self._update_status()
            logger.info("Carga cancelada por el usuario. Canales conservados: %d", len(self.channels))

    def set_channels(self, items: list[Channel], source: str):
        self.channels = items
        groups = sorted({c.group for c in items}, key=str.casefold)
        self.group_box["values"] = ["Todos los grupos"] + groups
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

    def play_selected(self):
        item = self.selected_channel()
        if item is None:
            messagebox.showinfo("Selecciona un elemento", "Selecciona una entrada de la tabla.")
            return
        if not shutil.which("mpv"):
            messagebox.showerror("Falta mpv", "Instala el reproductor con: sudo apt install mpv")
            return
        self.stop()
        try:
            # Native mpv video window, separate from Tkinter for X11/Wayland compatibility.
            self.player = subprocess.Popen(
                ["mpv", "--no-config", "--force-window=yes", "--title=IPTV Vídeo",
                 "--cache=yes", "--demuxer-readahead-secs=6", "--", item.url],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True)
            self.playing_channel = item
            self.playing_var.set(f"▶ {item.title}")
            self.status_var.set("Vídeo en ventana mpv. Doble clic en otra entrada para cambiar.")
            process = self.player
            threading.Thread(target=self._watch_player, args=(process,), daemon=True).start()
        except OSError:
            messagebox.showerror("Error", "No se pudo iniciar mpv.")

    def _watch_player(self, process: subprocess.Popen):
        rc = process.wait()
        logger.info("Reproductor finalizado con código %s", rc)
        def report():
            if self.player is process:
                self.player = None
                self.playing_channel = None
                self.playing_var.set("Sin reproducción")
                self.status_var.set("Emisión finalizada o no accesible." if rc else "Reproducción finalizada.")
        try:
            self.root.after(0, report)
        except RuntimeError:
            pass

    def stop(self):
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

    def on_close(self):
        self.stop()
        self.root.destroy()


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
