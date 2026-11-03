"""Read-only Xtream Codes API explorer with sanitized JSON responses.

Never display or export credentials, account data, server addresses or playback URLs.
API requests are restricted to player_api.php with allowlisted read operations.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from tkinter import ttk, filedialog, messagebox
import tkinter as tk
import threading

from xtream_probe import XtreamError, normalize_server, _NoRedirect
from xtream_profiles import profile_credentials, ProfileError

MAX_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_PREVIEW_CHARS = 100_000

# Read operations supported by common Xtream Codes Player APIs.
OPERATIONS = (
    "get_live_categories",
    "get_live_streams",
    "get_vod_categories",
    "get_vod_streams",
    "get_vod_info",
    "get_series_categories",
    "get_series",
    "get_series_info",
    "get_short_epg",
    "get_simple_data_table",
)
EXAMPLE = {
    "get_live_categories": "action=get_live_categories",
    "get_live_streams": "action=get_live_streams&category_id=1",
    "get_vod_categories": "action=get_vod_categories",
    "get_vod_streams": "action=get_vod_streams&category_id=1",
    "get_vod_info": "action=get_vod_info&vod_id=123",
    "get_series_categories": "action=get_series_categories",
    "get_series": "action=get_series&category_id=1",
    "get_series_info": "action=get_series_info&series_id=123",
    "get_short_epg": "action=get_short_epg&stream_id=123&limit=10",
    "get_simple_data_table": "action=get_simple_data_table&stream_id=123",
}
PARAMETERS = frozenset(("action", "series_id", "vod_id", "stream_id", "category_id", "limit"))
ID_PARAMETERS = frozenset(("series_id", "vod_id", "stream_id", "category_id", "limit"))

# Keys carrying account credentials, endpoints or private networking data.
PRIVATE_KEY_RE = re.compile(
    r"(^|_)(?:password|passwd|username|user_info|server_info|token|access_token|"
    r"refresh_token|secret|api_key|auth|authorization|url|link|host|hostname|"
    r"server|port|ip|email|mac|cookie|playlist|play_url|stream_url)(?:$|_)",
    re.IGNORECASE,
)
PRIVATE_URL_RE = re.compile(r"(?:https?|rtsp|rtmp|ftp)://[^\s\"'<>]+", re.IGNORECASE)
STREAM_PATH_RE = re.compile(r"/(?:live|movie|series)/[^/\s]+/[^/\s]+/", re.IGNORECASE)


def parse_query(query: str) -> dict[str, str]:
    """Parse user-defined query suffix, never accepting auth or arbitrary API paths."""
    value = (query or "").strip().lstrip("?&")
    if not value or len(value) > 2048:
        raise XtreamError("Especifica una consulta válida (máximo 2048 caracteres).")
    try:
        pairs = urllib.parse.parse_qsl(value, keep_blank_values=True,
                                       strict_parsing=True, max_num_fields=8)
    except ValueError:
        raise XtreamError("Parámetros de consulta no válidos.") from None
    result = {}
    for key, val in pairs:
        if key not in PARAMETERS or key in result:
            raise XtreamError("Parámetro no admitido o repetido. Usa action y los identificadores Xtream.")
        if key in ID_PARAMETERS and (not val.isascii() or not val.isdecimal() or len(val) > 12):
            raise XtreamError("Los identificadores y límites deben ser números enteros positivos.")
        result[key] = val
    if result.get("action") not in OPERATIONS:
        raise XtreamError("Acción no permitida. Selecciona una operación de solo lectura.")
    required = {
        "get_series_info": "series_id",
        "get_vod_info": "vod_id",
        "get_short_epg": "stream_id",
        "get_simple_data_table": "stream_id",
    }.get(result["action"])
    if required and required not in result:
        raise XtreamError("Esta operación necesita el parámetro " + required + ".")
    return result


def sanitize_response(value, *, secrets=(), depth=0):
    """Return a copy containing no raw URL strings, credentials or sensitive fields."""
    if depth > 30:
        return "[Profundidad omitida]"
    if isinstance(value, dict):
        return {
            str(k): ("[OCULTO]" if PRIVATE_KEY_RE.search(str(k))
                     else sanitize_response(v, secrets=secrets, depth=depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [sanitize_response(x, secrets=secrets, depth=depth + 1) for x in value]
    if isinstance(value, str):
        # Account secrets may appear in non-obviously named fields.
        if any(secret and (value == secret or (len(secret) >= 4 and secret in value)) for secret in secrets):
            return "[OCULTO]"
        if PRIVATE_URL_RE.search(value) or STREAM_PATH_RE.search(value):
            return PRIVATE_URL_RE.sub("[URL OCULTA]", STREAM_PATH_RE.sub("/[RUTA OCULTA]/", value))
        return value
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return "[Tipo omitido]"


def request_api(server, username, password, query, *, opener=None):
    """Perform one bounded GET; strip private data before returning to caller."""
    params = parse_query(query)
    base = normalize_server(server)
    args = {"username": username, "password": password, **params}
    url = base + "/player_api.php?" + urllib.parse.urlencode(args)
    client = opener or urllib.request.build_opener(_NoRedirect())
    request = urllib.request.Request(url, headers={
        "User-Agent": "IPTV-Video-Xtream-Explorer/1.0", "Accept": "application/json"})
    try:
        with client.open(request, timeout=35) as reply:
            raw = reply.read(MAX_RESPONSE_BYTES + 1)
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        # Never emit exceptions containing the credential-bearing request URL.
        raise XtreamError("No se pudo consultar la API (red, HTTP o tiempo de espera).") from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise XtreamError("La respuesta supera 16 MB; utiliza una consulta más concreta.")
    try:
        parsed = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, ValueError):
        raise XtreamError("La respuesta no es JSON válido.") from None
    host = urllib.parse.urlsplit(base).hostname or ""
    return sanitize_response(parsed, secrets=(username, password, host))


def open_api_explorer(master, profile_name):
    """A Postman-like read-only inspector using the already-stored Xtream profile."""
    win = tk.Toplevel(master)
    win.title("Explorar API Xtream Codes · " + profile_name)
    win.geometry("920x680")
    win.transient(master)

    top = ttk.Frame(win, padding=12)
    top.pack(fill="both", expand=True)
    ttk.Label(top, text="Perfil: " + profile_name + " · GET /player_api.php",
              font=("", 11, "bold")).pack(anchor="w")
    ttk.Label(top, text="Operaciones de solo lectura. Las credenciales se añaden internamente y nunca se muestran.",
              wraplength=850).pack(anchor="w", pady=(3, 10))
    toolbar = ttk.Frame(top)
    toolbar.pack(fill="x")
    operation = tk.StringVar(value="get_series_info")
    ttk.Label(toolbar, text="Operación:").pack(side="left")
    selected = ttk.Combobox(toolbar, textvariable=operation, values=OPERATIONS,
                            state="readonly", width=26)
    selected.pack(side="left", padx=8)
    query_var = tk.StringVar(value=EXAMPLE["get_series_info"])
    ttk.Label(top, text="Consulta (puedes editar los parámetros):").pack(anchor="w", pady=(10, 2))
    query_input = ttk.Entry(top, textvariable=query_var)
    query_input.pack(fill="x")
    ttk.Label(top, text="Ejemplo: action=get_series_info&series_id=123  ·  Utiliza un ID real del servidor.",
              foreground="#666666").pack(anchor="w", pady=(4, 8))
    status = tk.StringVar(value="Preparado. Los resultados se muestran con datos privados ocultos.")
    ttk.Label(top, textvariable=status, wraplength=850).pack(anchor="w", pady=(0, 6))
    frame = ttk.Frame(top)
    frame.pack(fill="both", expand=True)
    output = tk.Text(frame, wrap="none", state="disabled")
    y_scroll = ttk.Scrollbar(frame, orient="vertical", command=output.yview)
    x_scroll = ttk.Scrollbar(frame, orient="horizontal", command=output.xview)
    output.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
    output.grid(row=0, column=0, sticky="nsew")
    y_scroll.grid(row=0, column=1, sticky="ns")
    x_scroll.grid(row=1, column=0, sticky="ew")
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)

    state = {"result": None, "busy": False}
    row = ttk.Frame(top)
    row.pack(fill="x", pady=(9, 0))

    def update_example(_event=None):
        query_var.set(EXAMPLE[operation.get()])

    def execute(_event=None):
        if state["busy"]:
            return
        try:
            params = parse_query(query_var.get())
        except XtreamError as exc:
            status.set(str(exc))
            return
        expression = urllib.parse.urlencode(params)
        state["busy"] = True
        send_button.configure(state="disabled")
        status.set("Consultando " + params["action"] + "…")
        def worker():
            try:
                server, user, password = profile_credentials(profile_name)
                value = request_api(server, user, password, expression)
                text = json.dumps(value, ensure_ascii=False, indent=2)
                error = None
            except (ProfileError, XtreamError):
                text = None
                error = "Consulta fallida: comprueba el perfil, la acción y los identificadores."
            except Exception:
                text = None
                error = "No se pudo procesar la respuesta."
            def finish():
                if not win.winfo_exists():
                    return
                state["busy"] = False
                send_button.configure(state="normal")
                if error:
                    status.set(error)
                    return
                state["result"] = text
                output.configure(state="normal")
                output.delete("1.0", "end")
                output.insert("1.0", text[:MAX_PREVIEW_CHARS])
                output.configure(state="disabled")
                status.set("Respuesta recibida. " + str(len(text)) +
                           " caracteres; vista limitada a " + str(MAX_PREVIEW_CHARS) +
                           ". Puedes copiar/exportar el JSON filtrado completo.")
            try:
                master.after(0, finish)
            except RuntimeError:
                pass
        threading.Thread(target=worker, daemon=True).start()

    def copy_json():
        if state["result"] is None:
            return
        win.clipboard_clear()
        win.clipboard_append(state["result"])
        status.set("JSON filtrado copiado al portapapeles.")

    def export_json():
        if state["result"] is None:
            return
        path = filedialog.asksaveasfilename(parent=win, title="Exportar respuesta Xtream filtrada",
                                            defaultextension=".json", initialfile="xtream-api-respuesta.json",
                                            filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            from pathlib import Path
            Path(path).write_text(state["result"] + "\n", encoding="utf-8")
            status.set("Respuesta filtrada exportada.")
        except OSError:
            status.set("No se pudo guardar la respuesta.")

    selected.bind("<<ComboboxSelected>>", update_example)
    query_input.bind("<Return>", execute)
    send_button = ttk.Button(row, text="Enviar GET", command=execute)
    send_button.pack(side="left")
    ttk.Button(row, text="Copiar JSON filtrado", command=copy_json).pack(side="left", padx=7)
    ttk.Button(row, text="Exportar JSON filtrado…", command=export_json).pack(side="left")
    ttk.Label(row, text="Máx. 16 MB por respuesta", foreground="#666666").pack(side="right")
    return win
