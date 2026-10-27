"""Catálogo SQLite local para listas M3U grandes. No requiere dependencias externas."""
from __future__ import annotations

import json
import sqlite3

from media_classifier import classify
from pathlib import Path

DEFAULT_PATH = Path.home() / ".local" / "share" / "iptv-video" / "catalog.sqlite3"


class Catalog:
    def __init__(self, path=DEFAULT_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path))
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                group_name TEXT NOT NULL,
                attributes TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS favorites (url TEXT PRIMARY KEY, title TEXT NOT NULL, group_name TEXT NOT NULL, attributes TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_channels_group ON channels(group_name);
            CREATE INDEX IF NOT EXISTS idx_channels_url ON channels(url);
            CREATE VIRTUAL TABLE IF NOT EXISTS channels_fts USING fts5(
                title, group_name, attributes, content='channels', content_rowid='id',
                tokenize='unicode61 remove_diacritics 2'
            );
            CREATE TRIGGER IF NOT EXISTS channels_ai AFTER INSERT ON channels BEGIN
              INSERT INTO channels_fts(rowid,title,group_name,attributes)
              VALUES(new.id,new.title,new.group_name,new.attributes);
            END;
            CREATE TRIGGER IF NOT EXISTS channels_ad AFTER DELETE ON channels BEGIN
              INSERT INTO channels_fts(channels_fts,rowid,title,group_name,attributes)
              VALUES('delete',old.id,old.title,old.group_name,old.attributes);
            END;
        """)
        # Upgrade existing v14 databases in place; preserve channels and favorites.
        existing = {r[1] for r in self.db.execute("PRAGMA table_info(channels)")}
        columns = {
            "media_type": "TEXT NOT NULL DEFAULT 'unknown'",
            "series_title": "TEXT",
            "season_number": "INTEGER",
            "episode_number": "INTEGER",
            "classification_rule": "TEXT NOT NULL DEFAULT 'unknown'",
        }
        for name, definition in columns.items():
            if name not in existing:
                self.db.execute(f"ALTER TABLE channels ADD COLUMN {name} {definition}")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_channels_media ON channels(media_type)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_channels_series ON channels(media_type,series_title,season_number,episode_number)")
        # Existing v14 entries start with unknown; backfill in bounded batches.
        self.reclassify_unknown()
        self.db.commit()

    def reclassify_unknown(self, batch_size=1000):
        """Classify v14 rows safely, in bounded batches, without touching favorites."""
        last_id = 0
        while True:
            rows = self.db.execute(
                "SELECT id,title,url,group_name FROM channels WHERE id>? AND classification_rule='unknown' ORDER BY id LIMIT ?",
                (last_id, batch_size),
            ).fetchall()
            if not rows:
                break
            with self.db:
                self.db.executemany(
                    """UPDATE channels SET media_type=?,series_title=?,season_number=?,
                              episode_number=?,classification_rule=? WHERE id=?""",
                    ((*self._classification_values(title, group, url), id_)
                     for id_, title, url, group in rows),
                )
            last_id = rows[-1][0]

    @staticmethod
    def _classification_values(title, group, url):
        result = classify(title, group, url)
        return result.media_type, result.series_title, result.season_number, result.episode_number, result.rule

    def category_counts(self):
        counts = dict(self.db.execute(
            "SELECT media_type,COUNT(*) FROM channels GROUP BY media_type"
        ).fetchall())
        return {key: counts.get(key, 0) for key in ("tv","movie","series","event","unknown")}

    def reset(self):
        with self.db:
            self.db.execute("DELETE FROM channels")
        self.db.execute("PRAGMA optimize")

    def add(self, items):
        if not items:
            return
        with self.db:
            self.db.executemany(
                """INSERT INTO channels(title,url,group_name,attributes,media_type,series_title,
                   season_number,episode_number,classification_rule) VALUES(?,?,?,?,?,?,?,?,?)""",
                ((c.title, c.url, c.group, json.dumps(c.attributes, ensure_ascii=False),
                  *self._classification_values(c.title, c.group, c.url)) for c in items),
            )

    def count(self):
        return self.db.execute("SELECT count(*) FROM channels").fetchone()[0]

    def groups(self):
        return [r[0] for r in self.db.execute(
            "SELECT DISTINCT group_name FROM channels ORDER BY group_name COLLATE NOCASE")]

    @staticmethod
    def _match_query(text):
        # FTS5 prefix search; quote tokens so user inputs cannot become FTS syntax.
        import re
        tokens = re.findall(r"\w+", text, flags=re.UNICODE)
        return " AND ".join('"' + token.replace('"', '""') + '"*' for token in tokens)

    def search(self, text="", group="Todos los grupos", limit=3000, offset=0, favorites_only=False, media_type=None):
        if not isinstance(limit, int) or not 1 <= limit <= 10000:
            raise ValueError("Límite de resultados no válido")
        args = []
        join = ""
        conditions = []
        term = self._match_query(text)
        if term:
            join = " JOIN channels_fts ON channels_fts.rowid = c.id"
            conditions.append("channels_fts MATCH ?")
            args.append(term)
        if media_type is not None:
            if media_type not in ("tv","movie","series","event","unknown"):
                raise ValueError("Categoría no válida")
            conditions.append("c.media_type = ?")
            args.append(media_type)
        if favorites_only:
            conditions.append("EXISTS (SELECT 1 FROM favorites f WHERE f.url = c.url)")
        if group != "Todos los grupos":
            conditions.append("c.group_name = ?")
            args.append(group)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        base = " FROM channels c" + join + where
        total = self.db.execute("SELECT COUNT(*)" + base, args).fetchone()[0]
        rows = self.db.execute(
            "SELECT c.id,c.title,c.group_name,c.url,json_extract(c.attributes,'$.\"tvg-id\"')"
            + base + " ORDER BY c.id LIMIT ? OFFSET ?",
            args + [limit, offset],
        ).fetchall()
        return total, rows

    def favorite_urls(self):
        return {row[0] for row in self.db.execute("SELECT url FROM favorites")}

    def favorite_count(self):
        return self.db.execute("SELECT count(*) FROM favorites").fetchone()[0]

    def toggle_favorite(self, item):
        url, title, group, attributes = item.url, item.title, item.group, item.attributes
        with self.db:
            if self.db.execute("SELECT 1 FROM favorites WHERE url=?", (url,)).fetchone():
                self.db.execute("DELETE FROM favorites WHERE url=?", (url,))
            else:
                self.db.execute("INSERT INTO favorites VALUES(?,?,?,?)",
                                (url, title, group, json.dumps(attributes, ensure_ascii=False)))

    def add_favorites(self, items):
        with self.db:
            self.db.executemany("INSERT OR REPLACE INTO favorites VALUES(?,?,?,?)",
                ((c.url, c.title, c.group, json.dumps(c.attributes, ensure_ascii=False)) for c in items))

    def favorites(self):
        return [(r[1], r[0], r[2], json.loads(r[3])) for r in
                self.db.execute("SELECT url,title,group_name,attributes FROM favorites ORDER BY title")]

    def add_missing_favorites_to_channels(self, items):
        with self.db:
            for c in items:
                if not self.db.execute("SELECT 1 FROM channels WHERE url=? LIMIT 1", (c.url,)).fetchone():
                    self.db.execute("""INSERT INTO channels(title,url,group_name,attributes,media_type,series_title,
                                       season_number,episode_number,classification_rule) VALUES(?,?,?,?,?,?,?,?,?)""",
                                    (c.title,c.url,c.group,json.dumps(c.attributes, ensure_ascii=False),
                                     *self._classification_values(c.title,c.group,c.url)))

    def get(self, channel_id):
        row = self.db.execute(
            "SELECT title,url,group_name,attributes FROM channels WHERE id=?", (int(channel_id),)
        ).fetchone()
        if row is None:
            return None
        return row[0], row[1], row[2], json.loads(row[3])

    def close(self):
        self.db.close()
