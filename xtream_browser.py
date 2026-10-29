"""Browse native Xtream TV/VOD/series categories without altering M3U SQLite."""
from __future__ import annotations
import tkinter as tk
import threading
from tkinter import ttk, messagebox
from xtream_probe import _fetch, _fetch_series_info, _stream_collection, normalize_server, XtreamError
from xtream_stream import iter_json_array

MEDIA = {"TV": ("get_live_categories", "get_live_streams", "live"),
         "Películas": ("get_vod_categories", "get_vod_streams", "movie"),
         "Series": ("get_series_categories", "get_series", "series")}
MAX_ITEMS = 3000


def stream_path(base, user, password, media, ident, extension):
    """Build player URL locally; never store it in diagnostics or logs."""
    from urllib.parse import quote
    if not str(ident).isdigit():
        raise XtreamError("ID de contenido no válido.")
    ext = str(extension or "ts").lower().lstrip(".")
    if ext not in ("ts", "m3u8", "mp4", "mkv", "avi"):
        ext = "mp4" if media != "live" else "ts"
    return (base + "/" + media + "/" + quote(user, safe="") + "/" +
            quote(password, safe="") + "/" + str(ident) + "." + ext)


def browse_categories(base, user, password, media):
    action = MEDIA[media][0]
    rows = _fetch(base, user, password, action=action)
    if not isinstance(rows, list):
        raise XtreamError("Categorías Xtream no disponibles.")
    return [(str(row.get("category_id")), str(row.get("category_name") or "Sin nombre"))
            for row in rows if isinstance(row, dict) and row.get("category_id") is not None]


def browse_items(base, user, password, media, category_id):
    """Stream entire response but retain only requested category, bounded to MAX_ITEMS."""
    result = []
    count = 0
    with _stream_collection(base, user, password, MEDIA[media][1], timeout=60) as reply:
        for item in iter_json_array(reply):
            if not isinstance(item, dict) or str(item.get("category_id")) != str(category_id):
                continue
            count += 1
            if len(result) < MAX_ITEMS:
                result.append(item)
    return result, count


def series_episodes(base, user, password, series_id):
    info = _fetch_series_info(base, user, password, series_id)
    episodes = info.get("episodes") if isinstance(info, dict) else None
    if not isinstance(episodes, dict):
        raise XtreamError("El servidor no proporciona episodios de esta serie.")
    results = []
    for season, entries in episodes.items():
        if not isinstance(entries, list):
            continue
        for episode in entries:
            if isinstance(episode, dict):
                results.append((str(season), episode))
    return results


def open_xtream_browser(master, app, channel_type, server, username, password):
    base = normalize_server(server)
    win = tk.Toplevel(master)
    win.title("Explorar Xtream · TV / Películas / Series")
    win.geometry("1040x650")
    win.transient(master)
    frame = ttk.Frame(win, padding=10)
    frame.pack(fill="both", expand=True)
    mode = tk.StringVar(value="TV")
    status = tk.StringVar(value="Elige una categoría para cargar contenidos.")
    head = ttk.Frame(frame)
    head.pack(fill="x")
    ttk.Label(head,text="Tipo:").pack(side="left")
    selector = ttk.Combobox(head,values=list(MEDIA),textvariable=mode,state="readonly",width=16)
    selector.pack(side="left",padx=8)
    ttk.Label(frame,textvariable=status).pack(fill="x",pady=6)
    pane = ttk.Panedwindow(frame,orient="horizontal")
    pane.pack(fill="both",expand=True)
    left = ttk.Frame(pane)
    right = ttk.Frame(pane)
    pane.add(left,weight=1)
    pane.add(right,weight=3)
    categories = ttk.Treeview(left,columns=("name",),show="headings",selectmode="browse")
    categories.heading("name",text="Categorías del servidor")
    categories.pack(fill="both",expand=True)
    listing = ttk.Treeview(right,columns=("name","extra"),show="headings",selectmode="browse")
    listing.heading("name",text="Contenido")
    listing.heading("extra",text="Temporada / formato")
    listing.column("name",width=440)
    listing.column("extra",width=150)
    listing.pack(fill="both",expand=True)
    button_row = ttk.Frame(frame)
    button_row.pack(fill="x",pady=(7,0))
    entries = {}
    active_category = None
    current_series = None
    generation = [0]
    busy = [False]

    def async_job(work, callback):
        generation[0] += 1
        token = generation[0]
        status.set("Consultando el servidor…")
        def runner():
            try:
                result = work()
                failure = None
            except Exception:
                result, failure = None, "No fue posible consultar los datos Xtream."
            def finish():
                if not win.winfo_exists() or token != generation[0]:
                    return
                if failure:
                    status.set(failure)
                else:
                    callback(result)
            try:
                master.after(0,finish)
            except RuntimeError:
                pass
        threading.Thread(target=runner,daemon=True).start()

    def show_categories(rows):
        categories.delete(*categories.get_children())
        listing.delete(*listing.get_children())
        entries.clear()
        for i,(ident,name) in enumerate(rows):
            categories.insert("","end",iid=str(i),values=(name,),tags=(ident,))
        status.set(f"{len(rows)} categorías de {mode.get()}. Selecciona una.")

    def load_categories(_event=None):
        media = mode.get()
        async_job(lambda:browse_categories(base,username,password,media),show_categories)

    def show_items(payload):
        rows,total = payload
        listing.delete(*listing.get_children())
        entries.clear()
        for i,item in enumerate(rows):
            ident = str(i)
            entries[ident]=item
            listing.insert("","end",iid=ident,values=(item.get("name") or item.get("title") or "(Sin título)",""))
        status.set(f"{total} elementos en el grupo. Mostrando {len(rows)} (máximo {MAX_ITEMS}).")

    def select_category(_event=None):
        selected = categories.selection()
        if not selected:
            return
        ident = categories.item(selected[0],"tags")[0]
        media=mode.get()
        async_job(lambda:browse_items(base,username,password,media,ident),show_items)

    def show_episodes(rows):
        listing.delete(*listing.get_children())
        entries.clear()
        for i,(season,item) in enumerate(rows[:MAX_ITEMS]):
            ident=str(i)
            entries[ident]=item
            listing.insert("","end",iid=ident,values=(item.get("title") or item.get("name") or "(Episodio)",f"Temporada {season}"))
        status.set(f"{len(rows)} episodios (mostrando {min(len(rows),MAX_ITEMS)}). Doble clic para reproducir.")

    def open_item(_event=None):
        selected=listing.selection()
        if not selected:
            return
        item=entries.get(selected[0])
        if item is None:
            return
        media=mode.get()
        if media=="Series" and "series_id" in item:
            async_job(lambda:series_episodes(base,username,password,item["series_id"]),show_episodes)
            return
        if media=="TV":
            ident=item.get("stream_id")
            ext="ts"
        elif media=="Películas":
            ident=item.get("stream_id")
            ext=item.get("container_extension") or "mp4"
        else:
            ident=item.get("id")
            ext=item.get("container_extension") or "mp4"
        try:
            url=stream_path(base,username,password,MEDIA[media][2],ident,ext)
        except XtreamError:
            status.set("Este contenido no tiene una URL de reproducción válida.")
            return
        # Reuse existing playback and casting machinery, without inserting new M3U entries.
        channel=channel_type(item.get("title") or item.get("name") or "Xtream",url,
                            "Xtream "+media)
        app.play_item(channel)

    selector.bind("<<ComboboxSelected>>",load_categories)
    categories.bind("<<TreeviewSelect>>",select_category)
    listing.bind("<Double-1>",open_item)
    ttk.Button(button_row,text="Abrir / reproducir selección",command=open_item).pack(side="left")
    ttk.Button(button_row,text="Recargar categorías",command=load_categories).pack(side="left",padx=8)
    ttk.Label(button_row,text="Doble clic en una serie para ver episodios.").pack(side="right")
    load_categories()
    return win
