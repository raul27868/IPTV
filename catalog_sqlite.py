"""Catálogo SQLite local para listas M3U grandes. No requiere dependencias externas."""
from __future__ import annotations

import json
import sqlite3
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
        self.db.commit()

    def reset(self):
        with self.db:
            self.db.execute("DELETE FROM channels")
        self.db.execute("PRAGMA optimize")

    def add(self, items):
        if not items:
            return
        with self.db:
            self.db.executemany(
                "INSERT INTO channels(title,url,group_name,attributes) VALUES(?,?,?,?)",
                ((c.title, c.url, c.group, json.dumps(c.attributes, ensure_ascii=False))
                 for c in items),
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

    def search(self, text="", group="Todos los grupos", limit=3000, offset=0, favorites_only=False):
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
        if favorites_only:
            conditions.append("EXISTS (SELECT 1 FROM favorites f WHERE f.url = c.url)")
        if group != "Todos los grupos":
            conditions.append("c.group_name = ?")
            args.append(group)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        base = " FROM channels c" + join + where
        total = self.db.execute("SELECT COUNT(*)" + base, args).fetchone()[0]
        rows = self.db.execute(
            "SELECT c.id,c.title,c.group_name,json_extract(c.attributes,'$.\"tvg-id\"')"
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
                    self.db.execute("INSERT INTO channels(title,url,group_name,attributes) VALUES(?,?,?,?)",
                                    (c.title,c.url,c.group,json.dumps(c.attributes, ensure_ascii=False)))

    def get(self, channel_id):
        row = self.db.execute(
            "SELECT title,url,group_name,attributes FROM channels WHERE id=?", (int(channel_id),)
        ).fetchone()
        if row is None:
            return None
        return row[0], row[1], row[2], json.loads(row[3])

    def close(self):
        self.db.close()
