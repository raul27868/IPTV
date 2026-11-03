import io
import json
import unittest
from unittest.mock import patch
from xtream_api_explorer import parse_query, sanitize_response, request_api, XtreamError


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.close()


class FakeOpener:
    def __init__(self, data):
        self.data = data
        self.request = None
    def open(self, request, timeout=0):
        self.request = request
        return FakeResponse(json.dumps(self.data).encode("utf-8"))


class APIExplorerTests(unittest.TestCase):
    def test_query_accepts_series_info_and_normalized_suffix(self):
        self.assertEqual(parse_query("&action=get_series_info&series_id=123"),
                         {"action": "get_series_info", "series_id": "123"})
        self.assertEqual(parse_query("?action=get_vod_info&vod_id=456")["vod_id"], "456")

    def test_rejects_injected_credentials_and_unknown_actions(self):
        for query in (
            "action=get_series_info&series_id=23&username=hijack",
            "action=delete_user",
            "action=get_series_info",
            "action=get_series_info&series_id=123&series_id=234",
            "action=get_series_info&series_id=../../",
            "action=get_live_streams&password=stolen",
            "action=get_series_info&series_id=2&url=https%3A%2F%2Fexample.org",
        ):
            with self.subTest(query=query), self.assertRaises(XtreamError):
                parse_query(query)

    def test_redacts_account_fields_and_nested_urls(self):
        original = {"user_info": {"password": "secret", "username": "alice"},
                    "episodes": {"1": [{"title": "Capítulo 1",
                                         "direct_source": "http://private.example/secret",
                                         "stream_icon": "https://private.example/image.png",
                                         "extra": "rtsp://private.example/live"}]}}
        sanitized = sanitize_response(original, secrets=("secret","alice","private.example"))
        output = json.dumps(sanitized)
        self.assertNotIn("secret", output)
        self.assertNotIn("private.example", output)
        self.assertNotIn("alice", output)
        self.assertIn("Capítulo 1", output)

    def test_request_api_preserves_structure_but_never_reports_credentials(self):
        fake = FakeOpener({"episodes": {"1": [{"id": "44", "title": "Episodio",
                          "url": "https://provider.example/series/me/pass/44.mp4"}]},
                           "server_info": {"url": "provider.example"}})
        result = request_api("https://provider.example:8080", "me", "pass",
                             "action=get_series_info&series_id=4", opener=fake)
        url = fake.request.full_url
        self.assertIn("action=get_series_info", url)
        self.assertIn("series_id=4", url)
        self.assertIn("username=me", url)
        text = json.dumps(result)
        self.assertIn("Episodio", text)
        self.assertNotIn("provider.example", text)
        self.assertNotIn("pass", text)

    def test_cannot_export_raw_response_in_rejected_non_json(self):
        fake = FakeOpener({"url": "https://example.org/sensitive.m3u8"})
        value = request_api("https://example.org", "user", "password",
                            "action=get_live_categories", opener=fake)
        self.assertEqual(value["url"], "[OCULTO]")


if __name__ == "__main__":
    unittest.main()
