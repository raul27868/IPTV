"""Xtream metadata lookup for local read-only details dialogs.

URLs, provider credentials, and account information are redacted before display.
"""
from __future__ import annotations

from xtream_probe import XtreamError, _stream_collection, _fetch_series_info
from xtream_stream import iter_json_array
from xtream_api_explorer import request_api, sanitize_response


def get_item_details(server, user, password, media, item):
    """Retrieve the richest available provider metadata for the selected record."""
    if not isinstance(item, dict):
        raise XtreamError("Registro Xtream no válido.")
    if media == "Episodio":
        return sanitize_response(item, secrets=(user, password))
    if media == "Series":
        series_id = item.get("series_id")
        if not str(series_id).isdigit():
            raise XtreamError("La serie no contiene un identificador válido.")
        data = _fetch_series_info(server, user, password, series_id)
        return sanitize_response(data, secrets=(user, password))
    if media == "Películas":
        vod_id = item.get("stream_id")
        if not str(vod_id).isdigit():
            raise XtreamError("La película no contiene un identificador válido.")
        return request_api(server, user, password, "action=get_vod_info&vod_id=" + str(vod_id))
    if media == "TV":
        stream_id = item.get("stream_id")
        if not str(stream_id).isdigit():
            raise XtreamError("El canal no contiene un identificador válido.")
        # Xtream-compatible servers do not consistently provide a get_live_info
        # action. The standard get_live_streams response holds channel metadata.
        with _stream_collection(server, user, password, "get_live_streams", timeout=60) as reply:
            for record in iter_json_array(reply):
                if isinstance(record, dict) and str(record.get("stream_id")) == str(stream_id):
                    return sanitize_response(record, secrets=(user, password))
        # Some servers filter or rotate live lists. Show known metadata if absent.
        return sanitize_response(item, secrets=(user, password))
    raise XtreamError("Tipo de contenido no reconocido.")


def append_series_episodes(tree, entries, series_node, rows):
    """Append episodes as children without removing the surrounding series list.

    Compatible with ttk.Treeview and a minimal tree test double.
    """
    if tree.get_children(series_node):
        return len(tree.get_children(series_node))
    for index, (season, episode) in enumerate(rows):
        if not isinstance(episode, dict):
            continue
        node = f"{series_node}/ep/{index}"
        title = str(episode.get("title") or episode.get("name") or f"Episodio {index + 1}")
        tree.insert(series_node, "end", iid=node, text=title,
                    values=("Temporada " + str(season),))
        entries[node] = ("Episodio", episode)
    tree.item(series_node, open=True)
    return len(tree.get_children(series_node))
