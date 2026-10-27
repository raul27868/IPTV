import unittest
from app import parse_m3u

class ParseTests(unittest.TestCase):
    def test_example(self):
        from pathlib import Path
        path = Path(__file__).resolve().parent / 'index.ts'
        if path.exists():
            found = parse_m3u(path.read_bytes())
            self.assertEqual(len(found), 3)
            self.assertTrue(all(c.url.startswith('http') for c in found))

    def test_commas_in_quotes(self):
        text = '''#EXTM3U\n#EXTINF:-1 tvg-name="A, B" group-title="Noticias",Canal 1\nhttps://example.org/live.ts\n#EXTINF:-1,Segundo\nhttps://example.org/2\n'''
        items = parse_m3u(text)
        self.assertEqual(items[0].group, 'Noticias')
        self.assertEqual(items[0].title, 'Canal 1')
        self.assertEqual(items[0].attributes['tvg-name'], 'A, B')
        self.assertEqual(len(items), 2)

if __name__ == '__main__':
    unittest.main()
