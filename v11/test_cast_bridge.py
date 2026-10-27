import unittest
from unittest.mock import patch
from pathlib import Path
from cast_bridge import HLSBridge

class BridgeTests(unittest.TestCase):
    def test_missing_ffmpeg_cleanup(self):
        with patch('cast_bridge.shutil.which', return_value=None):
            b=HLSBridge('http://localhost/sample', '127.0.0.1')
            path=b.directory
            with self.assertRaisesRegex(RuntimeError, 'FFmpeg'):
                b.start()
            b.stop()
            self.assertFalse(path.exists())

    def test_lan_route_localhost(self):
        self.assertEqual(HLSBridge.lan_ip_for('127.0.0.1'), '127.0.0.1')

if __name__ == '__main__': unittest.main()
