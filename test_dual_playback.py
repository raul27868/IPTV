"""Regression checks for automatic startup and independent mpv/Cast outputs."""
import unittest
from unittest.mock import MagicMock, patch
from app import VideoIPTVApp


class DualPlaybackTests(unittest.TestCase):
    def make_app(self, mode="Local (mpv)", also_local=False):
        app = VideoIPTVApp.__new__(VideoIPTVApp)
        app.cast_var = MagicMock()
        app.cast_var.get.return_value = mode
        app.cast_also_local = MagicMock()
        app.cast_also_local.get.return_value = also_local
        app._stop_cast_only = MagicMock()
        app._play_local = MagicMock()
        app.play_cast = MagicMock()
        return app

    def test_local_only(self):
        app = self.make_app()
        item = object()
        app.play_item(item)
        app._stop_cast_only.assert_called_once_with()
        app._play_local.assert_called_once_with(item)
        app.play_cast.assert_not_called()

    def test_cast_only(self):
        app = self.make_app("Google TV", False)
        item = object()
        app.play_item(item)
        app._play_local.assert_not_called()
        app.play_cast.assert_called_once_with(item, keep_local=False)

    def test_cast_plus_mpv(self):
        app = self.make_app("Google TV", True)
        item = object()
        app.play_item(item)
        app._play_local.assert_called_once_with(item)
        app.play_cast.assert_called_once_with(item, keep_local=True)

    def test_full_stop_stops_both_independent_outputs(self):
        app = self.make_app()
        app._stop_local_only = MagicMock()
        app.playing_var = MagicMock()
        app.stop()
        app._stop_cast_only.assert_called_once_with()
        app._stop_local_only.assert_called_once_with()

    def test_cast_stop_preserves_mpv_process(self):
        app = self.make_app()
        app.cast_session = 1
        app.bridge = None
        app.cast_device = None
        app.player = MagicMock()
        app.player.poll.return_value = None
        app.playing_var = MagicMock()
        app._stop_cast_only = VideoIPTVApp._stop_cast_only.__get__(app)
        app._stop_cast_only()
        self.assertEqual(app.cast_session, 2)
        self.assertIsNotNone(app.player)
        app.playing_var.set.assert_not_called()


if __name__ == "__main__":
    unittest.main()
