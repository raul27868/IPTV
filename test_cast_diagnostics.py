"""Regression tests for failure classification and non-streaming HEAD probe."""
import io
import unittest
import urllib.error
from unittest.mock import patch

from cast_diagnostics import (
    SourceUnavailable, preflight_source, ffmpeg_diagnosis,
    playback_mode_label, cast_receiver_diagnosis,
)
from cast_bridge import HLSBridge, BridgeStartError


class FakeReply(io.BytesIO):
    def __init__(self, status):
        super().__init__(b"")
        self.status = status
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.close()


class FakeClient:
    def __init__(self, status):
        self.status = status
        self.request = None
    def open(self, request, timeout):
        self.request = request
        if self.status >= 400:
            raise urllib.error.HTTPError(request.full_url, self.status,
                                         "error", None, None)
        return FakeReply(self.status)


class CastDiagnosticTests(unittest.TestCase):
    def test_successful_head_does_not_read_video(self):
        client = FakeClient(200)
        result = preflight_source("https://example.test/live/private/stream.ts",
                                  opener=client)
        self.assertEqual(result, "reachable")
        self.assertEqual(client.request.get_method(), "HEAD")

    def test_source_503_classified_without_private_url(self):
        client = FakeClient(503)
        with self.assertRaises(SourceUnavailable) as cm:
            preflight_source("http://example.test/live/secret/stream.ts",
                             opener=client)
        self.assertEqual(cm.exception.code, 503)
        self.assertNotIn("secret", str(cm.exception))

    def test_unsupported_head_does_not_block_ffmpeg(self):
        for status in (401, 403, 404, 405, 302):
            with self.subTest(status=status):
                self.assertEqual(preflight_source("http://example.test/live/stream.ts",
                                                 opener=FakeClient(status)), "inconclusive")

    def test_ffmpeg_origin_vs_codec_vs_network(self):
        self.assertEqual(ffmpeg_diagnosis(
            "[http @ 0xa] HTTP error 503 Service Unavailable")[0], "origin")
        self.assertEqual(ffmpeg_diagnosis(
            "Error opening input: Server returned 5XX Server Error reply")[0], "ffmpeg")
        self.assertEqual(ffmpeg_diagnosis("Unknown decoder 'foo'")[0], "codec")
        self.assertEqual(ffmpeg_diagnosis("Connection refused")[0], "network")

    def test_errors_do_not_echo_private_urls(self):
        text = "[http @ 0xa] HTTP error 503 https://host/live/alice/secret/12.ts"
        self.assertNotIn("alice", ffmpeg_diagnosis(text)[1])

    def test_mode_label_exact_fallback(self):
        self.assertEqual(playback_mode_label(True, "video/mp4"),
                         (False, "Directo (Chromecast recibe la URL)"))
        self.assertIn("MPEG-TS", playback_mode_label(True, "video/mp2t")[1])
        self.assertIn("formato desconocido", playback_mode_label(True, None)[1])
        self.assertTrue(playback_mode_label(False, "video/mp4")[0])

    def test_receiver_unknown_codec_is_not_asserted(self):
        category, text = cast_receiver_diagnosis("IDLE", "ERROR")
        self.assertEqual(category, "receiver")
        self.assertIn("Posibles causas", text)

    def test_preflight_rejects_before_starting_ffmpeg_or_server(self):
        with patch("cast_bridge.shutil.which", return_value="/usr/bin/ffmpeg"), \\
             patch("cast_bridge.preflight_source", side_effect=SourceUnavailable(503)), \\
             patch("cast_bridge.subprocess.Popen") as popen:
            bridge = HLSBridge("http://example.test/private/url", "127.0.0.1")
            directory = bridge.directory
            with self.assertRaises(BridgeStartError) as cm:
                bridge.start()
            self.assertEqual(cm.exception.category, "origin")
            popen.assert_not_called()
            self.assertFalse(directory.exists())


if __name__ == "__main__":
    unittest.main()
