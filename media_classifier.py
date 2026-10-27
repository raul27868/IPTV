"""Deterministic and conservative IPTV content classification."""
import re
import unicodedata
from dataclasses import dataclass

@dataclass(frozen=True)
class Classification:
    media_type: str
    series_title: str | None = None
    season_number: int | None = None
    episode_number: int | None = None
    rule: str = "unknown"

def _norm(value):
    return "".join(c for c in unicodedata.normalize("NFKD", str(value or "").casefold()) if not unicodedata.combining(c))

_EPISODE = re.compile(r"(?i)(?<![a-z0-9])s(\d{1,3})\s*e(\d{1,4})(?!\d)|(?<!\d)(\d{1,3})x(\d{1,4})(?!\d)")
_SERIES = re.compile(r"(?<![a-z])(?:series?|temporadas?|episodios?|tv shows?)(?![a-z])")
_MOVIES = re.compile(r"(?<![a-z])(?:peliculas?|movies?|filmes?|cinema|cine|vod)(?![a-z])")
_EVENTS = re.compile(r"(?<![a-z])(?:eventos?|events?|ppv)(?![a-z])")
_TV = re.compile(r"(?<![a-z])(?:live|directo|canales?|television|tv)(?![a-z])")

def classify(title, group="", url="", attributes=None):
    """Return metadata inferred from title/group; never alter source data."""
    title = str(title or "")
    group_norm = _norm(group)
    match = _EPISODE.search(title)
    if match:
        season, episode = (int(match.group(1)), int(match.group(2))) if match.group(1) else (int(match.group(3)), int(match.group(4)))
        series_title = title[:match.start()].strip(" -_.[]()")
        return Classification("series", series_title or title, season, episode, "episode_pattern")
    if _SERIES.search(group_norm):
        return Classification("series", title, None, None, "series_group")
    if _MOVIES.search(group_norm):
        return Classification("movie", rule="movie_group")
    if _EVENTS.search(group_norm):
        return Classification("event", rule="event_group")
    if _TV.search(group_norm):
        return Classification("tv", rule="tv_group")
    return Classification("unknown")
