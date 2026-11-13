"""Regression checks for restored favorites serialization compatibility."""
import unittest

from app import Channel, parse_m3u, serialize_favorites


class FavoritesCompatibilityTests(unittest.TestCase):
    def test_serialize_empty_favorites(self):
        self.assertEqual(serialize_favorites([]), "#EXTM3U\n")

    def test_round_trip_channel_objects(self):
        favorites = [
            Channel("Canal uno", "https://example.test/live/1.ts", "Noticias",
                    {"tvg-id": "id-1", "tvg-name": "Uno"}),
            Channel('Cine "Plus"', "https://example.test/movie/2.mp4", "Películas"),
        ]
        result = serialize_favorites(favorites)
        parsed = parse_m3u(result)
        self.assertEqual(len(parsed), 2)
        self.assertEqual([c.title for c in parsed], ["Canal uno", "Cine 'Plus'"])
        self.assertEqual([c.url for c in parsed], [c.url for c in favorites])
        self.assertEqual(parsed[0].group, "Noticias")
        self.assertEqual(parsed[0].attributes["tvg-id"], "id-1")

    def test_catalog_tuple_format(self):
        entries = [
            ("Uno", "https://example.test/uno.ts", "Grupo", {"tvg-id": "abc"}),
            ("Dos", "https://example.test/dos.ts", "Otro", {}),
        ]
        parsed = parse_m3u(serialize_favorites(entries))
        self.assertEqual(len(parsed), 2)
        self.assertEqual([c.url for c in parsed], [x[1] for x in entries])
        self.assertEqual(parsed[1].group, "Otro")

    def test_export_does_not_mutate_input_attributes(self):
        attrs = {"group-title": "Anterior", "tvg-id": "abc"}
        favorite = Channel("Uno", "https://example.test/a.ts", "Nuevo", attrs)
        serialize_favorites([favorite])
        self.assertEqual(attrs["group-title"], "Anterior")

    def test_title_newline_does_not_inject_m3u_lines(self):
        favorite = Channel("Canal\n#EXTINF:-1,Hack", "https://example.test/a.ts")
        parsed = parse_m3u(serialize_favorites([favorite]))
        self.assertEqual(len(parsed), 1)
        self.assertNotIn("\n", parsed[0].title)


if __name__ == "__main__":
    unittest.main()
