import io
import unittest
from xtream_stream import iter_json_array
from xtream_probe import probe_catalog, XtreamError

class StreamTests(unittest.TestCase):
    def test_split_unicode_and_large_list(self):
        import json
        records = [{"name":"Película ñ","category_id":"3"} for _ in range(4000)]
        data = json.dumps(records,ensure_ascii=False).encode("utf-8")
        class Stream:
            def __init__(self,b):
                self.source=io.BytesIO(b)
            def read(self,n):
                return self.source.read(min(n,17))
        got=list(iter_json_array(Stream(data)))
        self.assertEqual(got,records)

    def test_invalid_json(self):
        with self.assertRaises(XtreamError):
            list(iter_json_array(io.BytesIO(b'[{"a":1},not-json]')))

    def test_catalog_counts_and_sample(self):
        def fake(server,user,password,action=None,timeout=None,series_id=None):
            if action=="get_live_streams":
                return [{"name":"TV","category_id":"12"}]
            if action=="get_vod_streams":
                return [{"name":"Film A","category_id":"2"},{"name":"Film B","category_id":"2"}]
            if action=="get_series":
                return [{"name":"Series A","category_id":"4","series_id":123}]
            if action=="get_series_info":
                self.assertEqual(series_id,123)
                return {"episodes":{"1":[{"id":"1"},{"id":"2"}],"2":[{"id":"3"}]}}
            raise AssertionError(action)
        report=probe_catalog("https://example.test","user","secret",fetcher=fake)
        self.assertEqual(report["collections"]["movies"]["count"],2)
        self.assertEqual(report["collections"]["movies"]["distinct_category_ids"],1)
        self.assertEqual(report["series_sample"]["seasons_count"],2)
        self.assertEqual(report["series_sample"]["episode_count"],3)
        self.assertNotIn("secret",str(report))
        self.assertNotIn("Film A",str(report))

if __name__=="__main__":
    unittest.main()
