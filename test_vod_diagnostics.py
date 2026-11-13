"""VOD identification, privacy-preserving metrics and correct Cast semantics."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from vod_diagnostics import (
    VODSessionReport, content_kind, cast_stream_type, parse_ffmpeg_progress,
)
from cast_bridge import HLSSnapshot


class VODDiagnosticTests(unittest.TestCase):
    def test_xtream_category_and_explicit_kind(self):
        self.assertEqual(content_kind(SimpleNamespace(group="Xtream Películas", attributes={})), "movie")
        self.assertEqual(content_kind(SimpleNamespace(group="Xtream Episodio", attributes={})), "episode")
        self.assertEqual(content_kind(SimpleNamespace(group="Xtream TV", attributes={})), "live")
        self.assertEqual(content_kind(SimpleNamespace(group="General", attributes={
            "iptv_media_kind": "episode"})), "episode")

    def test_cast_semantics_differentiate_direct_vod_from_sliding_hls(self):
        self.assertEqual(cast_stream_type("movie", transcoded=False), "BUFFERED")
        self.assertEqual(cast_stream_type("episode", transcoded=False), "BUFFERED")
        self.assertEqual(cast_stream_type("movie", transcoded=True), "LIVE")
        self.assertEqual(cast_stream_type("live", transcoded=False), "LIVE")

    def test_ffmpeg_progress_last_values_and_missing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "progress.txt"
            self.assertEqual(parse_ffmpeg_progress(path), {})
            path.write_text(
                "frame=10\nfps=10.0\nspeed=2.0x\nout_time_us=1000000\nprogress=continue\n"
                "frame=21\nfps=22.5\nspeed=0.97x\nout_time_us=2400000\nprogress=continue\n",
                encoding="utf-8")
            result = parse_ffmpeg_progress(path)
            self.assertEqual(result["frame"], 21)
            self.assertEqual(result["speed"], .97)
            self.assertEqual(result["output_seconds"], 2.4)

    def test_json_no_credentials_urls_or_sensitive_metadata(self):
        report = VODSessionReport(kind="movie", mode="hls-stable", started_at=100)
        for code in (200, 404, 404, 503, 999):
            report.record_response(code)
        snap = HLSSnapshot(True, 2, 1, 3, "part_000007.ts")
        report.sample(snapshot=snap, state="BUFFERING", position=74.2,
                      progress={"speed": .8, "output_seconds": 78.4}, elapsed=80)
        report.finish()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.json"
            report.write(path)
            text = path.read_text()
            exported = json.loads(text)
        self.assertEqual(exported["http_response_counts"]["404"], 2)
        self.assertEqual(exported["http_response_counts"]["other"], 1)
        self.assertEqual(exported["samples"][0]["receiver_position_s"], 74.2)
        self.assertNotIn("part_000007", text)
        self.assertNotIn("http://", text)
        self.assertNotIn("username", text)

    def test_bounds_samples(self):
        report = VODSessionReport(kind="episode", mode="direct")
        for i in range(730):
            report.sample(elapsed=i)
        self.assertEqual(len(report.samples), 720)
        self.assertEqual(report.samples[0]["elapsed_s"], 10)


if __name__ == "__main__":
    unittest.main()
