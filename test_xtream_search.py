import io
import json
import unittest
from unittest.mock import patch

from xtream_search import title_matches, scan_streams, search_global
from xtream_probe import XtreamError


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.close()


class XtreamSearchTests(unittest.TestCase):
    def test_accent_case_and_name_title(self):
        self.assertTrue(title_matches({"name": "FÚTBOL · España"}, "futbol"))
        self.assertTrue(title_matches({"title": "Película Ñ"}, "PELICULA n"))
        self.assertFalse(title_matches({"name": "Tenis"}, "futbol"))

    def test_content_search_checks_entries_beyond_display_limit(self):
        entries = [{"name": "Evento ordinario", "stream_id": i, "category_id": "7"}
                   for i in range(3200)]
        entries.append({"name": "Final exclusiva", "stream_id": 3201, "category_id": "7"})
        entries.append({"name": "Final ajena", "stream_id": 3202, "category_id": "8"})
        body = json.dumps(entries).encode("utf-8")
        with patch("xtream_search._stream_collection",return_value=FakeResponse(body)):
            matches, count = scan_streams("https://example.test","user","password",
                                          "get_live_streams", "final", category_id="7")
        self.assertEqual(count, 1)
        self.assertEqual(matches[0]["stream_id"], 3201)

    def test_global_search_classifies_three_collections(self):
        data = {
            "get_live_streams": [{"name":"Final deportiva","stream_id":11}],
            "get_vod_streams": [{"name":"La Gran Final","stream_id":22,
                                 "container_extension":"mkv"}],
            "get_series": [{"name":"Final del camino","series_id":33}],
        }
        def fake_stream(base,user,password,action,timeout=60):
            return FakeResponse(json.dumps(data[action]).encode("utf-8"))
        with patch("xtream_search._stream_collection",side_effect=fake_stream):
            matches, counts, errors = search_global("https://example.test","u","secret","FINAL")
        self.assertEqual([m for m,_ in matches],["TV","Películas","Series"])
        self.assertEqual(counts,{"TV":1,"Películas":1,"Series":1})
        self.assertEqual(errors,{})
        self.assertEqual(matches[-1][1]["series_id"],33)
        self.assertNotIn("secret",json.dumps(matches))

    def test_search_global_rejects_short_input(self):
        with self.assertRaises(XtreamError):
            search_global("https://example.test","u","p","a")

    def test_partial_failure_does_not_hide_other_results(self):
        def fake_stream(base,user,password,action,timeout=60):
            if action == "get_vod_streams":
                raise XtreamError("response unavailable")
            return FakeResponse(json.dumps([{"name":"Final","stream_id":5}]).encode())
        with patch("xtream_search._stream_collection",side_effect=fake_stream):
            result,counts,errors=search_global("https://example.test","u","p","final")
        self.assertEqual(len(result),2)
        self.assertIsNone(counts["Películas"])
        self.assertIn("Películas",errors)


if __name__ == "__main__":
    unittest.main()
