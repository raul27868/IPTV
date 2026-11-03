import io
import unittest
from unittest.mock import patch

from xtream_details import get_item_details, append_series_episodes
from xtream_probe import XtreamError


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.close()


class FakeTree:
    def __init__(self):
        self.rows = {"0": [], "1": [], "2": []}
        self.created = []
        self.opened = {}
    def get_children(self, parent=""):
        return tuple(self.rows.get(parent, ()))
    def insert(self, parent, position, iid, **kwargs):
        self.rows[parent].append(iid)
        self.rows[iid] = []
        self.created.append((parent, iid, kwargs))
    def item(self, node, **kwargs):
        self.opened[node] = kwargs


class XtreamDetailsTests(unittest.TestCase):
    def test_episode_tree_keeps_siblings_and_preserves_seasons(self):
        tree = FakeTree()
        entries = {"0": ("Series", {"series_id": 1}),
                   "1": ("Series", {"series_id": 2}),
                   "2": ("Series", {"series_id": 3})}
        episodes = [("1", {"id": "101", "title": "Primero"}),
                    ("1", {"id": "102", "title": "Segundo"}),
                    ("2", {"id": "103", "title": "Tercero"})]
        count = append_series_episodes(tree, entries, "1", episodes)
        self.assertEqual(count, 3)
        self.assertEqual(len(tree.get_children("1")), 3)
        self.assertEqual(tree.get_children("0"), ())
        self.assertEqual(tree.get_children("2"), ())
        self.assertEqual(entries["1/ep/2"][0], "Episodio")
        self.assertEqual(tree.created[-1][2]["values"], ("Temporada 2",))
        self.assertTrue(tree.opened["1"]["open"])
        self.assertEqual(append_series_episodes(tree, entries, "1", episodes), 3)
        self.assertEqual(len(tree.created), 3)

    def test_series_details_call_native_info(self):
        with patch("xtream_details._fetch_series_info",
                   return_value={"info":{"name":"Serie de prueba"},
                                 "episodes":{"1":[{"id":"100"}]}}) as fn:
            metadata = get_item_details("https://example.test", "u", "p",
                                        "Series", {"series_id": 42})
        fn.assert_called_once_with("https://example.test", "u", "p", 42)
        self.assertEqual(metadata["info"]["name"], "Serie de prueba")

    def test_vod_details_call_native_info(self):
        with patch("xtream_details.request_api",
                   return_value={"info":{"plot":"Sinopsis"}}) as fn:
            metadata = get_item_details("https://example.test", "u", "p",
                                        "Películas", {"stream_id": 77})
        self.assertEqual(metadata["info"]["plot"], "Sinopsis")
        self.assertIn("action=get_vod_info&vod_id=77", fn.call_args.args[-1])

    def test_tv_details_retrieve_full_record_and_redact_urls(self):
        import json
        response = FakeResponse(json.dumps([
            {"stream_id": 1, "name": "Otro"},
            {"stream_id": 2, "name": "Canal", "stream_icon": "https://private.test/logo.png",
             "tv_archive": 1, "category_id": "8"},
        ]).encode("utf-8"))
        with patch("xtream_details._stream_collection", return_value=response):
            metadata = get_item_details("https://example.test", "u", "p",
                                        "TV", {"stream_id": 2})
        self.assertEqual(metadata["tv_archive"], 1)
        self.assertNotIn("private.test", str(metadata))

    def test_episode_details_display_existing_metadata(self):
        metadata = get_item_details("https://example.test", "u", "p",
                                    "Episodio", {"id":"9", "title":"Capítulo",
                                                "direct_source":"https://private.test/secret"})
        self.assertEqual(metadata["title"], "Capítulo")
        self.assertNotIn("private.test", str(metadata))

    def test_invalid_identifier(self):
        with self.assertRaises(XtreamError):
            get_item_details("https://example.test", "u", "p",
                             "Series", {"series_id": "../../"})
if __name__ == "__main__":
    unittest.main()
