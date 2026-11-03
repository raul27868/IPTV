"""Regression tests: source selection must not reset the existing M3U catalog."""
import unittest
from unittest.mock import MagicMock
from app import VideoIPTVApp


class SourceSelectionTests(unittest.TestCase):
    def make_app(self, source):
        app = VideoIPTVApp.__new__(VideoIPTVApp)
        app.source_var = MagicMock()
        app.source_var.get.return_value = source
        app.url_controls = MagicMock()
        app.file_controls = MagicMock()
        app.xtream_controls = MagicMock()
        app.xtream_host = MagicMock()
        app.m3u_panel = MagicMock()
        app.playback_actions = MagicMock()
        app.catalog = MagicMock()
        return app

    def test_switch_url_and_file_preserves_existing_catalog(self):
        for source in ("URL M3U", "Archivo M3U"):
            with self.subTest(source=source):
                app = self.make_app(source)
                app._change_source()
                app.m3u_panel.pack.assert_called_once()
                app.catalog.reset.assert_not_called()
                app.catalog.close.assert_not_called()
                app.xtream_host.pack_forget.assert_called_once()

    def test_source_switch_does_not_stop_playback(self):
        app = self.make_app("URL M3U")
        app.stop = MagicMock()
        app._change_source()
        app.stop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
