#!/usr/bin/env python3
"""Explorador M3U y reproductor de audio IPTV para Ubuntu."""
from __future__ import annotations

import os
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
from urllib.parse import urlparse

USER_AGENT = "Mozilla/5.0 IPTV-Audio-Explorer/1.0"
MAX_PLAYLIST_BYTES = 40 * 1024 * 1024
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


class AudioIPTVApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("IPTV Audio · Explorador M3U")
        root.geometry("1080x690")
        root.minsize(760, 480)
        self.channels: list[Channel] = []
        self.visible: list[int] = []
        self.player: subprocess.Popen | None = None
        self.playing_channel: Channel | None = None
        self.request_number = 0
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
        ttk.Button(r, text="Abrir archivo…", command=self.load_local).pack(side="left", padx=(8, 0))

        filters = ttk.Frame(shell)
        filters.pack(fill="x", pady=(8, 8))
        ttk.Label(filters, text="Buscar:").pack(side="left")
        ttk.Entry(filters, textvariable=self.search_var, width=38).pack(side="left", padx=(6, 16), fill="x", expand=True)
        ttk.Label(filters, text="Grupo:").pack(side="left")
        self.group_box = ttk.Combobox(filters, textvariable=self.group_var, state="readonly", width=25)
        self.group_box.pack(side="left", padx=(6, 0))
        self.group_box["values"] = ["Todos los grupos"]
        self.group_box.bind("<<ComboboxSelected>>", lambda _: self.render())
        self.search_var.trace_add("write", lambda *_: self.render())

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
        ttk.Button(actions, text="▶ Reproducir audio", command=self.play_selected).pack(side="left")
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

    def render(self):
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
            self.table.insert("", "end", iid=str(i), values=(ch.title, ch.group, ch.attributes.get("tvg-id", "")))
        if self.channels:
            self.status_var.set(f"{len(self.visible)} entradas visibles · {len(self.channels)} entradas en total")
        self.show_details()

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

    def load_local(self):
        path = filedialog.askopenfilename(title="Seleccionar lista M3U", filetypes=[("Listas M3U / ejemplo TS", "*.m3u *.m3u8 *.ts *.txt"), ("Todos", "*")])
        if not path:
            return
        try:
            if Path(path).stat().st_size > MAX_PLAYLIST_BYTES:
                raise ValueError("La lista supera el límite de 40 MB.")
            self.set_channels(parse_m3u(Path(path).read_bytes()), Path(path).name)
        except (OSError, ValueError) as exc:
            messagebox.showerror("No se pudo leer", str(exc))

    def load_remote(self):
        url = self.url_var.get().strip()
        parsed = urlparse(url)
        if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
            messagebox.showerror("URL no válida", "Indica una URL HTTP o HTTPS válida para descargar la lista.")
            return
        self.request_number += 1
        request_id = self.request_number
        self.status_var.set("Descargando la lista…")

        def work():
            try:
                request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
                with urllib.request.urlopen(request, timeout=25) as response:
                    data = response.read(MAX_PLAYLIST_BYTES + 1)
                if len(data) > MAX_PLAYLIST_BYTES:
                    raise ValueError("La lista supera el límite de 40 MB.")
                items = parse_m3u(data)
                self.root.after(0, lambda: self.set_channels(items, parsed.hostname or "URL") if request_id == self.request_number else None)
            except (urllib.error.URLError, OSError, ValueError) as exc:
                # Never display exceptions containing the full URL; credentials might be embedded.
                error_type = type(exc).__name__
                self.root.after(0, lambda: self._load_error(error_type) if request_id == self.request_number else None)
        threading.Thread(target=work, daemon=True).start()

    def _load_error(self, kind: str):
        self.status_var.set("Error al cargar la lista")
        messagebox.showerror("Error de descarga", f"No se pudo obtener la lista ({kind}). Comprueba la dirección, la conexión y las credenciales.")

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
            # --no-video disables video decoding/display. Never run a shell with URL arguments.
            self.player = subprocess.Popen(
                ["mpv", "--no-config", "--no-video", "--force-window=no", "--audio-display=no",
                 "--cache=yes", "--demuxer-readahead-secs=6", "--really-quiet", "--", item.url],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True)
            self.playing_channel = item
            self.playing_var.set(f"▶ {item.title}")
            self.status_var.set("Reproduciendo audio. Doble clic en otra entrada para cambiar.")
            process = self.player
            threading.Thread(target=self._watch_player, args=(process,), daemon=True).start()
        except OSError:
            messagebox.showerror("Error", "No se pudo iniciar mpv.")

    def _watch_player(self, process: subprocess.Popen):
        rc = process.wait()
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
    AudioIPTVApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
