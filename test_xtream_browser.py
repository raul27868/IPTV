import io
import json
import unittest
from unittest.mock import patch
from xtream_browser import browse_categories, browse_items, series_episodes, stream_path

class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.close()

class BrowseTests(unittest.TestCase):
    def test_categories(self):
        with patch("xtream_browser._fetch",return_value=[
            {"category_id":"7","category_name":"Deportes"}]):
            self.assertEqual(browse_categories("https://example.test","u","p","TV"),
                             [("7","Deportes")])

    def test_stream_group_filter(self):
        body = json.dumps([{"name":"A","category_id":"4","stream_id":1},
                           {"name":"B","category_id":"5","stream_id":2}]).encode()
        with patch("xtream_browser._stream_collection",return_value=FakeResponse(body)):
            items,total=browse_items("https://example.test","u","p","Películas","4")
            self.assertEqual(total,1)
            self.assertEqual(items[0]["name"],"A")

    def test_series_episodes(self):
        with patch("xtream_browser._fetch_series_info",return_value={
            "episodes":{"1":[{"id":"10","title":"Episodio 1"}],
                        "2":[{"id":"11","title":"Episodio 2"}]}}):
            episodes=series_episodes("https://example.test","u","p",12)
            self.assertEqual([x[0] for x in episodes],["1","2"])

    def test_playback_url(self):
        link=stream_path("https://example.test","user","p@ss word","movie",42,"mp4")
        self.assertIn("/movie/user/p%40ss%20word/42.mp4",link)

if __name__=="__main__":
    unittest.main()
