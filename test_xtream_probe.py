import tempfile
import unittest
from pathlib import Path
from xtream_probe import normalize_server, probe, save_report, XtreamError

class XtreamProbeTests(unittest.TestCase):
    def test_normalization(self):
        self.assertEqual(normalize_server("iptv.example:8080/"), "http://iptv.example:8080")
        self.assertEqual(normalize_server("https://iptv.example/player_api.php"), "https://iptv.example")
        with self.assertRaises(XtreamError):
            normalize_server("http://user:pass@iptv.example/")
        with self.assertRaises(XtreamError):
            normalize_server("http://iptv.example/get.php?username=x")

    def test_safe_report(self):
        calls=[]
        def fake(server, user, password, action=None):
            calls.append(action)
            self.assertEqual(user, "private-username")
            self.assertEqual(password, "private-password")
            if action is None:
                return {"user_info":{"auth":1,"status":"Active","username":user,"password":password},
                        "server_info":{"url":"private-server"}}
            return [{"category_id":"42","category_name":"Sports","parent_id":0}]
        report=probe("https://iptv.example", "private-username", "private-password", fetcher=fake)
        self.assertTrue(report["connection"]["authenticated"])
        self.assertEqual(report["categories"]["tv"]["count"],1)
        self.assertEqual(calls,[None,"get_live_categories","get_vod_categories","get_series_categories"])
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/"report.json"
            save_report(report,out)
            text=out.read_text()
            for secret in ("private-username","private-password","private-server","iptv.example","Sports"):
                self.assertNotIn(secret,text)

    def test_bad_login_no_category_calls(self):
        def fake(server, user, password, action=None):
            self.assertIsNone(action)
            return {"user_info":{"auth":0,"status":"Disabled"}}
        report=probe("example.test", "u", "p", fetcher=fake)
        self.assertFalse(report["connection"]["authenticated"])
        self.assertEqual(report["categories"],{})

if __name__=="__main__":
    unittest.main()
