"""Regression tests for legacy Chromecast HLS stability and monitoring."""
from __future__ import annotations

import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from cast_bridge import HLSBridge, HLSSnapshot, HLS_PROFILES
from cast_monitor import assess_hls, format_age


def sample(*, ffmpeg=True, segment=1.0, request=2.0, playlist=1.0):
    return HLSSnapshot(ffmpeg, segment, playlist, request, "part_000042.ts")


class StabilityTests(unittest.TestCase):
    def test_profiles_are_distinct_and_bounded(self):
        self.assertEqual(HLS_PROFILES["standard"], (2, 6, 3))
        self.assertEqual(HLS_PROFILES["stable"], (3, 12, 8))
        self.assertEqual(HLS_PROFILES["light"], (3, 12, 8))
        with self.assertRaises(ValueError):
            HLSBridge("http://example.test/stream.ts", "127.0.0.1", profile="invalid")

    def test_snapshot_reports_segment_age_without_urls(self):
        bridge = HLSBridge("http://user:secret@example.test/stream.ts", "127.0.0.1",
                           profile="stable")
        try:
            (bridge.stream_dir / "part_000042.ts").write_bytes(b"segment")
            bridge.process = MagicMock()
            bridge.process.poll.return_value = None
            with bridge._telemetry_lock:
                bridge._last_segment_request = time.monotonic() - 5
                bridge._last_playlist_request = time.monotonic() - 3
                bridge._last_segment_name = "part_000042.ts"
            snap = bridge.snapshot()
            self.assertTrue(snap.ffmpeg_running)
            self.assertLess(snap.latest_segment_age, 5)
            self.assertGreater(snap.last_segment_request_age, 4)
            self.assertNotIn("secret", str(snap))
        finally:
            bridge.process.poll.return_value = 0
            bridge.stop()

    def test_warmup_avoids_false_positive(self):
        status, _ = assess_hls(sample(segment=60, request=None), elapsed=20)
        self.assertEqual(status, "initializing")

    def test_ffmpeg_exited_is_source_stopped(self):
        status, _ = assess_hls(sample(ffmpeg=False), elapsed=100)
        self.assertEqual(status, "source_stopped")

    def test_segment_generation_stalled(self):
        status, _ = assess_hls(sample(segment=45, request=3), elapsed=120)
        self.assertEqual(status, "source_stalled")

    def test_receiver_no_longer_requests_segments(self):
        status, _ = assess_hls(sample(segment=2, request=55), elapsed=120)
        self.assertEqual(status, "receiver_stalled")

    def test_receiver_never_requested_segments(self):
        status, _ = assess_hls(sample(segment=2, request=None), elapsed=100)
        self.assertEqual(status, "receiver_stalled")

    def test_receiver_idle_and_healthy(self):
        self.assertEqual(assess_hls(sample(), elapsed=120, cast_state="IDLE")[0],
                         "receiver_idle")
        self.assertEqual(assess_hls(sample(), elapsed=120, cast_state="PLAYING")[0],
                         "healthy")

    def test_ffmpeg_arguments_match_profile_without_network(self):
        # A fake encoder writes a valid initial HLS playlist and one segment.
        # No upstream streaming or Google Cast device is needed.
        for profile, seconds, size, threshold in (
            ("standard", "2", "6", "3"),
            ("stable", "3", "12", "8"),
            ("light", "3", "12", "8"),
        ):
            with self.subTest(profile=profile):
                captured = []
                proc = MagicMock()
                proc.poll.return_value = None
                server = MagicMock()
                server.server_port = 45678
                def fake_popen(args, **kwargs):
                    captured.extend(args)
                    Path(args[-1]).write_text("#EXTM3U\\n", encoding="utf-8")
                    pattern = args[args.index("-hls_segment_filename") + 1]
                    Path(pattern.replace("%06d", "000000")).write_bytes(b"segment")
                    return proc
                with (patch("cast_bridge.shutil.which", return_value="/usr/bin/ffmpeg"),
                      patch("cast_bridge.preflight_source", return_value="reachable"),
                      patch.object(HLSBridge, "lan_ip_for", return_value="127.0.0.1"),
                      patch("cast_bridge.http.server.ThreadingHTTPServer", return_value=server),
                      patch("cast_bridge.subprocess.Popen", side_effect=fake_popen)):
                    bridge = HLSBridge("https://example.test/video", "127.0.0.1", profile=profile)
                    try:
                        result = bridge.start(timeout=1)
                        self.assertIn("live.m3u8", result)
                        self.assertEqual(captured[captured.index("-hls_time")+1], seconds)
                        self.assertEqual(captured[captured.index("-hls_list_size")+1], size)
                        self.assertEqual(captured[captured.index("-hls_delete_threshold")+1], threshold)
                        self.assertIn(f"n_forced*{seconds}", captured[captured.index("-force_key_frames")+1])
                        if profile == "light":
                            self.assertIn("fps=25", captured[captured.index("-vf")+1])
                            self.assertIn("854:480", captured[captured.index("-vf")+1])
                            self.assertEqual(captured[captured.index("-b:v")+1], "1200k")
                            self.assertEqual(captured[captured.index("-b:a")+1], "96k")
                        else:
                            self.assertEqual(captured[captured.index("-b:v")+1], "2200k")
                    finally:
                        proc.poll.return_value = 0
                        bridge.stop()

    def test_age_formatter(self):
        self.assertEqual(format_age(None), "sin solicitudes")
        self.assertEqual(format_age(4.9), "hace 4 s")


if __name__ == "__main__":
    unittest.main()
