import json
import os
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from app import VideoIPTVApp

class MPVIPCTests(unittest.TestCase):
    def test_loadfile_command_received(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d)/'sock')
            ready = threading.Event()
            commands = []
            def serve():
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                    listener.bind(path)
                    listener.listen(1)
                    ready.set()
                    conn, _ = listener.accept()
                    with conn:
                        data = b''
                        while b'\n' not in data:
                            data += conn.recv(4096)
                        commands.append(json.loads(data))
                        conn.sendall(b'{"error":"success","data":null}\n')
            t = threading.Thread(target=serve)
            t.start()
            self.assertTrue(ready.wait(2))
            fake = SimpleNamespace(mpv_socket=path, player=SimpleNamespace(poll=lambda: None))
            self.assertTrue(VideoIPTVApp._mpv_command(fake, ['loadfile','https://example.org/stream.ts','replace']))
            t.join(2)
            self.assertEqual(commands, [{'command':['loadfile','https://example.org/stream.ts','replace']}])

    def test_unavailable_socket_returns_false(self):
        fake = SimpleNamespace(mpv_socket='/tmp/nonexistent-iptv-test.sock',player=SimpleNamespace(poll=lambda: None))
        self.assertFalse(VideoIPTVApp._mpv_command(fake,['loadfile','https://example.org','replace']))

if __name__ == '__main__':
    unittest.main()
