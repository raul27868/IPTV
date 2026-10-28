import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xtream_profiles import load_profiles, save_profile, profile_credentials, delete_profile

class FakeKeyring:
    priority = 1
    def __init__(self):
        self.data = {}
    def get_keyring(self):
        return self
    def set_password(self, service, name, password):
        self.data[(service,name)] = password
    def get_password(self, service, name):
        return self.data.get((service,name))
    def delete_password(self, service, name):
        self.data.pop((service,name))

class ProfileTests(unittest.TestCase):
    def test_round_trip_and_no_plaintext_password(self):
        fake=FakeKeyring()
        with tempfile.TemporaryDirectory() as folder, patch("xtream_profiles._keyring",return_value=fake):
            path=Path(folder)/"xtream-profiles.json"
            save_profile("Casa","https://server.example:443","private-user","private-secret",path)
            text=path.read_text()
            self.assertNotIn("private-secret",text)
            self.assertEqual(load_profiles(path)["Casa"]["username"],"private-user")
            self.assertEqual(profile_credentials("Casa",path),
                             ("https://server.example:443","private-user","private-secret"))
            delete_profile("Casa",path)
            self.assertEqual(load_profiles(path),{})
            self.assertIsNone(fake.get_password("iptv-video-xtream","Casa"))

if __name__ == "__main__":
    unittest.main()
