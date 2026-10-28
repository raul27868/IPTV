import sqlite3
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path

from media_classifier import classify
from catalog_sqlite import Catalog


@dataclass
class Entry:
    title: str
    url: str
    group: str = ""
    attributes: dict = field(default_factory=dict)


class ClassificationTests(unittest.TestCase):
    def test_episode_patterns_and_priority(self):
        c = classify("La Casa S02E003", "Películas")
        self.assertEqual((c.media_type, c.series_title, c.season_number, c.episode_number),
                         ("series", "La Casa", 2, 3))
        c = classify("Una serie 1x08", "Sin grupo")
        self.assertEqual((c.media_type, c.season_number, c.episode_number), ("series", 1, 8))

    def test_conservative_categories(self):
        self.assertEqual(classify("Canal fútbol", "TV Deportes").media_type, "tv")
        self.assertEqual(classify("Especial", "Eventos deportivos").media_type, "event")
        self.assertEqual(classify("Película", "Cine HD").media_type, "movie")
        self.assertEqual(classify("Drama", "Series").media_type, "series")
        self.assertEqual(classify("2026 Mundial", "Sin grupo").media_type, "unknown")


class SchemaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "old.sqlite3"

    def tearDown(self):
        self.temp.cleanup()

    def test_incremental_categories_and_favorites(self):
        catalog = Catalog(self.path)
        items = [
            Entry("Fútbol HD", "http://localhost/tv", "TV Deportes"),
            Entry("Serie X S01E02", "http://localhost/s", "VOD"),
            Entry("Peli X", "http://localhost/p", "Películas"),
            Entry("Final", "http://localhost/e", "Eventos"),
            Entry("Desconocido", "http://localhost/u", "Otros"),
        ]
        catalog.add(items)
        catalog.toggle_favorite(items[1])
        self.assertEqual(catalog.category_counts(), {"tv": 1, "movie": 1, "series": 1, "event": 1, "unknown": 1})
        self.assertEqual(catalog.search(media_type="series")[0], 1)
        self.assertEqual(catalog.search("serie", media_type="series")[0], 1)
        catalog.close()
        catalog = Catalog(self.path)
        self.assertEqual(catalog.category_counts()["series"], 1)
        self.assertEqual(catalog.favorite_count(), 1)
        catalog.reset()
        self.assertEqual(catalog.favorite_count(), 1)
        catalog.close()

    def test_series_navigation(self):
        catalog = Catalog(self.path)
        catalog.add([
            Entry("Mar S01E02", "http://localhost/2", "Series"),
            Entry("Mar S01E01", "http://localhost/1", "Series"),
            Entry("Mar S02E01", "http://localhost/3", "Series"),
            Entry("Cine X", "http://localhost/m", "Películas"),
        ])
        self.assertEqual(catalog.series_titles(), [("Mar", 3)])
        self.assertEqual(catalog.series_seasons("Mar"), [(1, 2), (2, 1)])
        rows = catalog.series_episodes("Mar", 1)
        self.assertEqual([row[1] for row in rows], ["Mar S01E01", "Mar S01E02"])
        catalog.close()

    def test_upgrade_existing_v14_catalog_in_place(self):
        con = sqlite3.connect(self.path)
        con.executescript("""
            CREATE TABLE channels (id INTEGER PRIMARY KEY,title TEXT NOT NULL,url TEXT NOT NULL,
              group_name TEXT NOT NULL,attributes TEXT NOT NULL);
            CREATE TABLE favorites (url TEXT PRIMARY KEY,title TEXT NOT NULL,group_name TEXT NOT NULL,
              attributes TEXT NOT NULL);
            INSERT INTO channels(title,url,group_name,attributes) VALUES
              ('Viaje S03E04','http://example/ep','Series','{}'),
              ('Canal 24','http://example/live','TV España','{}');
            INSERT INTO favorites VALUES ('http://example/live','Canal 24','TV España','{}');
        """)
        con.commit()
        con.close()
        catalog = Catalog(self.path)
        self.assertEqual(catalog.count(), 2)
        self.assertEqual(catalog.favorite_count(), 1)
        self.assertEqual(catalog.category_counts()["series"], 1)
        self.assertEqual(catalog.category_counts()["tv"], 1)
        catalog.close()
        # Reopening should not reclassify correctly migrated rows.
        catalog = Catalog(self.path)
        self.assertEqual(catalog.count(), 2)
        catalog.close()


if __name__ == "__main__":
    unittest.main()
