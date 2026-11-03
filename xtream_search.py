"""Client-side search over the standard Xtream Player API collections.

Most Xtream-compatible servers expose list actions, not a portable global
search action. Scan JSON incrementally and retain only matching metadata.
"""
from __future__ import annotations

import unicodedata

from xtream_probe import _stream_collection, XtreamError, normalize_server
from xtream_stream import iter_json_array

SEARCH_LIMIT = 3000
ACTIONS = (
    ("TV", "get_live_streams"),
    ("Películas", "get_vod_streams"),
    ("Series", "get_series"),
)


def normalized(value):
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def title_matches(item, query):
    """Case- and accent-insensitive title search, regardless of Xtream media type."""
    title = item.get("name") or item.get("title") or ""
    return normalized(query) in normalized(title)


def scan_streams(base, user, password, action, query, *, category_id=None, limit=SEARCH_LIMIT):
    """Stream a collection; return (matches, total_matches) without keeping all rows."""
    if not isinstance(limit, int) or not 1 <= limit <= SEARCH_LIMIT:
        raise ValueError("Límite de búsqueda no válido")
    matches = []
    total = 0
    with _stream_collection(base, user, password, action, timeout=60) as response:
        for item in iter_json_array(response):
            if not isinstance(item, dict):
                continue
            if category_id is not None and str(item.get("category_id")) != str(category_id):
                continue
            if query and not title_matches(item, query):
                continue
            total += 1
            if len(matches) < limit:
                # Keep only metadata needed for navigation/playback; discard
                # unnecessary URLs and account-related provider fields.
                matches.append({key: item[key] for key in (
                    "name", "title", "stream_id", "series_id", "category_id",
                    "container_extension", "id") if key in item})
    return matches, total


def search_global(server, username, password, query, *, limit=SEARCH_LIMIT):
    """Search TV, VOD and series using the standard list endpoints.

    Returns ([(media_type, item), ...], counts_by_media, errors_by_media).
    A provider-specific action=search is intentionally not assumed.
    """
    if len(normalized(query).strip()) < 2:
        raise XtreamError("Escribe al menos dos caracteres para la búsqueda global.")
    base = normalize_server(server)
    matches = []
    counts = {}
    errors = {}
    for media, action in ACTIONS:
        try:
            # Continue counting beyond the visible result cap.
            found, total = scan_streams(base, username, password, action, query,
                                        limit=limit)
            counts[media] = total
            space = max(0, limit - len(matches))
            matches.extend((media, item) for item in found[:space])
        except (XtreamError, OSError, ValueError):
            counts[media] = None
            errors[media] = "No se pudo consultar esta colección."
    return matches, counts, errors
