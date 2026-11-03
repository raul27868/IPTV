"""Browse native Xtream TV/VOD/series categories without altering M3U SQLite."""
from __future__ import annotations
import tkinter as tk
import threading
import json
from tkinter import ttk, messagebox
from xtream_probe import _fetch, _fetch_series_info, _stream_collection, normalize_server, XtreamError
from xtream_stream import iter_json_array
from xtream_search import scan_streams, search_global
from xtream_details import get_item_details, append_series_episodes

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


def browse_items(base, user, password, media, category_id, query=""):
    """Search all entries in a category, including beyond its first 3,000 rows."""
    return scan_streams(base, user, password, MEDIA[media][1], query,
                        category_id=category_id, limit=MAX_ITEMS)


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
    """Legacy auxiliary window, retained for backward compatibility."""
    win = tk.Toplevel(master)
    win.title("Explorar Xtream · TV / Películas / Series")
    win.geometry("1040x650")
    win.transient(master)
    mount_xtream_browser(win, app, channel_type, server, username, password)
    return win


def mount_xtream_browser(parent, app, channel_type, server, username, password):
    """Mount Xtream browsing into any existing container, including the main UI."""
    base = normalize_server(server)
    frame = ttk.Frame(parent, padding=10)
    frame.pack(fill="both", expand=True)
    master = parent.winfo_toplevel()
    mode = tk.StringVar(value="TV")
    status = tk.StringVar(value="Elige una categoría para cargar contenidos.")
    head = ttk.Frame(frame)
    head.pack(fill="x")
    ttk.Label(head,text="Tipo:").pack(side="left")
    selector = ttk.Combobox(head,values=list(MEDIA),textvariable=mode,state="readonly",width=16)
    selector.pack(side="left",padx=8)
    ttk.Label(head, text="Buscar en todo Xtream:").pack(side="left", padx=(18, 5))
    global_query = tk.StringVar()
    global_entry = ttk.Entry(head, textvariable=global_query, width=34)
    global_entry.pack(side="left", fill="x", expand=True)
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
    listing = ttk.Treeview(right, columns=("extra",), show="tree headings", selectmode="browse")
    listing.heading("#0", text="Contenido")
    listing.heading("extra", text="ID / Temporada")
    listing.column("#0", width=440, minwidth=220)
    listing.column("extra", width=150)
    local_bar = ttk.Frame(right)
    local_bar.pack(fill="x", pady=(0, 5))
    ttk.Label(local_bar, text="Buscar en Contenido:").pack(side="left")
    local_query = tk.StringVar()
    local_entry = ttk.Entry(local_bar, textvariable=local_query)
    local_entry.pack(side="left", fill="x", expand=True, padx=(7, 0))
    listing.pack(fill="both",expand=True)
    button_row = ttk.Frame(frame)
    button_row.pack(fill="x",pady=(7,0))
    entries = {}
    selected_category = [None]
    episode_rows = [None]
    expanded_series = {}
    generation = [0]

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
                if not frame.winfo_exists() or token != generation[0]:
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
        selected_category[0] = None
        episode_rows[0] = None
        local_query.set("")
        categories.delete(*categories.get_children())
        listing.delete(*listing.get_children())
        entries.clear()
        for i,(ident,name) in enumerate(rows):
            categories.insert("","end",iid=str(i),values=(name,),tags=(ident,))
        status.set(f"{len(rows)} categorías de {mode.get()}. Selecciona una.")

    def load_categories(_event=None):
        media = mode.get()
        async_job(lambda:browse_categories(base,username,password,media),show_categories)

    def render_rows(rows, total, *, global_results=False):
        listing.delete(*listing.get_children())
        entries.clear()
        expanded_series.clear()
        for i, payload in enumerate(rows):
            media, item = payload if global_results else (mode.get(), payload)
            ident = str(i)
            entries[ident] = (media, item)
            name = item.get("name") or item.get("title") or "(Sin título)"
            ident_value = item.get("series_id") if media == "Series" else item.get("stream_id")
            label = ("[" + media + "] " if global_results else "") + str(name)
            listing.insert("", "end", iid=ident, text=label, values=(
                "ID: " + str(ident_value if ident_value is not None else "—"),))
        status.set(f"{total} coincidencias. Mostrando {len(rows)} (máximo {MAX_ITEMS}).")

    def show_items(payload):
        rows, total = payload
        episode_rows[0] = None
        render_rows(rows, total)

    def show_global(payload):
        rows, counts, errors = payload
        episode_rows[0] = None
        render_rows(rows, sum(count for count in counts.values() if count is not None),
                    global_results=True)
        details = " · ".join(f"{media}: {n if n is not None else 'error'}"
                             for media, n in counts.items())
        status.set(f"Búsqueda global: {details}. Mostrando {len(rows)}." +
                   (" Algunas colecciones fallaron." if errors else ""))

    def search_category(_event=None):
        category = selected_category[0]
        if category is None:
            status.set("Selecciona primero una categoría.")
            return
        media = mode.get()
        query = local_query.get().strip()
        async_job(lambda: browse_items(base, username, password, media, category, query),
                  show_items)

    def select_category(_event=None):
        selected = categories.selection()
        if not selected:
            return
        selected_category[0] = categories.item(selected[0], "tags")[0]
        local_query.set("")
        search_category()

    def search_everywhere(_event=None):
        query = global_query.get().strip()
        if len(query) < 2:
            status.set("Escribe al menos dos caracteres para buscar en todo Xtream.")
            return
        async_job(lambda: search_global(base, username, password, query), show_global)

    def clear_local_search():
        local_query.set("")
        search_category()

    def show_episodes(rows, parent_node):
        if not listing.exists(parent_node):
            return
        expanded_series[parent_node] = rows
        count = append_series_episodes(listing, entries, parent_node, rows[:MAX_ITEMS])
        listing.see(parent_node)
        status.set(f"{count} episodios desplegados. El resto de contenidos sigue visible.")

    def filter_episodes(_event=None):
        # For the current category this searches the *complete* Xtream list,
        # not just the first visible entries; expanded tree nodes are rebuilt.
        search_category()

    def open_item(_event=None):
        selected=listing.selection()
        if not selected:
            return
        selection = entries.get(selected[0])
        if selection is None:
            return
        media, item = selection
        if media == "Series" and "series_id" in item:
            node = selected[0]
            if node in expanded_series:
                listing.item(node, open=not bool(listing.item(node, "open")))
                return
            series_id = item["series_id"]
            async_job(lambda: series_episodes(base, username, password, series_id),
                      lambda rows: show_episodes(rows, node))
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
            url=stream_path(base,username,password,"series" if media == "Episodio" else MEDIA[media][2],ident,ext)
        except XtreamError:
            status.set("Este contenido no tiene una URL de reproducción válida.")
            return
        # Reuse existing playback and casting machinery, without inserting new M3U entries.
        channel=channel_type(item.get("title") or item.get("name") or "Xtream",url,
                            "Xtream "+media)
        app.play_item(channel)

    def show_full_info(selection):
        media, item = selection
        popup = tk.Toplevel(master)
        popup.title("Información Xtream · " + str(item.get("name") or item.get("title") or media)[:80])
        popup.geometry("820x620")
        popup.transient(master)
        container = ttk.Frame(popup, padding=10)
        container.pack(fill="both", expand=True)
        ttk.Label(container, text="Metadatos del servidor · campos sensibles y enlaces privados ocultos",
                  wraplength=780).pack(anchor="w", pady=(0, 6))
        box = ttk.Frame(container)
        box.pack(fill="both", expand=True)
        output = tk.Text(box, wrap="none")
        vscroll = ttk.Scrollbar(box, orient="vertical", command=output.yview)
        hscroll = ttk.Scrollbar(box, orient="horizontal", command=output.xview)
        output.configure(yscrollcommand=vscroll.set, xscrollcommand=hscroll.set)
        output.grid(row=0, column=0, sticky="nsew")
        vscroll.grid(row=0, column=1, sticky="ns")
        hscroll.grid(row=1, column=0, sticky="ew")
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        output.insert("1.0", "Consultando detalles del servidor…")
        output.configure(state="disabled")
        def worker():
            try:
                data = get_item_details(base, username, password, media, item)
                display = json.dumps(data, ensure_ascii=False, indent=2)
            except Exception:
                display = "No se pudieron obtener los detalles del servidor."
            def apply():
                if not popup.winfo_exists():
                    return
                output.configure(state="normal")
                output.delete("1.0", "end")
                output.insert("1.0", display)
                output.configure(state="disabled")
            try:
                master.after(0, apply)
            except RuntimeError:
                pass
        threading.Thread(target=worker, daemon=True).start()

    def context_details(event):
        node = listing.identify_row(event.y)
        if not node:
            return
        listing.selection_set(node)
        selection = entries.get(node)
        if selection is not None:
            show_full_info(selection)

    listing.bind("<Button-3>", context_details)
    selector.bind("<<ComboboxSelected>>", load_categories)
    categories.bind("<<TreeviewSelect>>", select_category)
    listing.bind("<Double-1>", open_item)
    global_entry.bind("<Return>", search_everywhere)
    local_entry.bind("<Return>", filter_episodes)
    ttk.Button(head, text="Buscar global", command=search_everywhere).pack(side="left", padx=(6, 0))
    ttk.Button(local_bar, text="Buscar", command=filter_episodes).pack(side="left", padx=(5, 0))
    ttk.Button(local_bar, text="Limpiar", command=clear_local_search).pack(side="left", padx=(4, 0))
    ttk.Button(button_row,text="Abrir / reproducir selección",command=open_item).pack(side="left")
    ttk.Button(button_row,text="Recargar categorías",command=load_categories).pack(side="left",padx=8)
    ttk.Label(button_row,text="Doble clic en una serie para ver episodios.").pack(side="right")
    frame.play_selection = open_item
    load_categories()
    return frame
