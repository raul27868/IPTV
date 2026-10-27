import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from catalog_sqlite import Catalog


@dataclass
class Entry:
    title: str
    url: str
    group: str = "Sin grupo"
    attributes: dict = field(default_factory=dict)


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.catalog = Catalog(Path(self.tmp.name) / "test.sqlite3")

    def tearDown(self):
        self.catalog.close()
        self.tmp.cleanup()

    def test_import_search_details_and_persistence(self):
        self.catalog.add([
            Entry("La Primera HD", "http://localhost/one", "España", {"tvg-id": "la1.es"}),
            Entry("Noticias 24", "http://localhost/two", "Informativos"),
            Entry("H2O S01E01", "http://localhost/three", "Series"),
        ])
        self.assertEqual(self.catalog.count(), 3)
        self.assertEqual(self.catalog.search("prim")[0], 1)
        total, rows = self.catalog.search("noticias", "Informativos")
        self.assertEqual(total, 1)
        self.assertEqual(self.catalog.get(rows[0][0])[1], "http://localhost/two")
        self.assertEqual(self.catalog.search("ausente")[0], 0)
        self.catalog.close()
        self.catalog = Catalog(Path(self.tmp.name) / "test.sqlite3")
        self.assertEqual(self.catalog.count(), 3)

    def test_reset_and_unicode(self):
        self.catalog.add([Entry("Música Española", "http://localhost/a", "España")])
        self.assertEqual(self.catalog.search("musica")[0], 1)
        self.catalog.reset()
        self.assertEqual(self.catalog.count(), 0)
        self.assertEqual(self.catalog.search("musica")[0], 0)

    def test_favorites_survive_reset_and_can_be_filtered(self):
        entry = Entry("Canal favorito", "http://localhost/fav", "España")
        self.catalog.add([entry])
        self.catalog.toggle_favorite(entry)
        self.assertEqual(self.catalog.favorite_count(), 1)
        self.assertEqual(self.catalog.search(favorites_only=True)[0], 1)
        self.catalog.reset()
        self.assertEqual(self.catalog.favorite_count(), 1)
        self.catalog.add_missing_favorites_to_channels([entry])
        self.assertEqual(self.catalog.search(favorites_only=True)[0], 1)
        self.catalog.toggle_favorite(entry)
        self.assertEqual(self.catalog.favorite_count(), 0)

    def test_large_batches_and_pagination(self):
        self.catalog.add([Entry(f"Canal {i:05d}", f"http://localhost/{i}", "TV")
                          for i in range(12000)])
        self.assertEqual(self.catalog.count(), 12000)
        total, rows = self.catalog.search("canal", limit=100, offset=100)
        self.assertEqual(total, 12000)
        self.assertEqual(len(rows), 100)
        self.assertEqual(self.catalog.get(rows[0][0])[0], "Canal 00100")


if __name__ == "__main__":
    unittest.main()
