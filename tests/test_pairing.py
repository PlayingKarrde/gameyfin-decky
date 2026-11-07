import json
import os
import sys
import time
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))

from gameyfin import pairing  # noqa: E402
from gameyfin.common import phoneform  # noqa: E402


def req(url, data=None):
    body = json.dumps(data).encode() if data is not None else None
    r = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"} if body else {})
    try:
        with urllib.request.urlopen(r, timeout=5) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


class PairingTests(unittest.TestCase):
    def setUp(self):
        self.got = []

        def submit(url, token, sgdb_key):
            if token == "bad":
                raise ValueError("API token was rejected")
            self.got.append((url, token, sgdb_key))
            return "Connected."

        self.s = pairing.session("http://gf.local:8080", submit).start()
        self.base = f"http://127.0.0.1:{self.s.port}"
        self.addCleanup(self.s.stop)

    def test_flow(self):
        code, page = req(f"{self.base}/{self.s.code.lower()}")  # case-insensitive
        self.assertEqual(code, 200)
        self.assertIn('value="http://gf.local:8080"', page)
        self.assertEqual(req(f"{self.base}/WRONG1")[0], 404)
        code, body = req(f"{self.base}/{self.s.code}", {"server_url": "http://gf.local:8080", "token": "bad"})
        self.assertFalse(json.loads(body)["ok"])
        self.assertEqual(self.s.state, "waiting")
        code, body = req(f"{self.base}/{self.s.code}", {"server_url": "http://gf.local:8080", "token": "gf_pat_x"})
        self.assertTrue(json.loads(body)["ok"])
        self.assertEqual(self.got, [("http://gf.local:8080", "gf_pat_x", "")])
        self.assertEqual(self.s.status()["state"], "done")
        time.sleep(0.2)
        with self.assertRaises(OSError):  # server is gone
            urllib.request.urlopen(f"{self.base}/{self.s.code}", timeout=2)

    def test_locks_after_guessing(self):
        for _ in range(phoneform.MAX_BAD_REQUESTS):
            req(f"{self.base}/AAAAAA")
        self.assertEqual(self.s.state, "locked")

    def test_sgdb_key_only(self):
        code, body = req(f"{self.base}/{self.s.code}", {"server_url": "", "token": "", "sgdb_key": "abc"})
        self.assertTrue(json.loads(body)["ok"])
        self.assertEqual(self.got, [("", "", "abc")])

    def test_needs_something(self):
        code, body = req(f"{self.base}/{self.s.code}", {"server_url": "http://gf.local:8080", "token": ""})
        self.assertFalse(json.loads(body)["ok"])
        code, body = req(f"{self.base}/{self.s.code}", {"server_url": "", "token": "gf_pat_x"})
        self.assertEqual(json.loads(body)["message"], "Server URL is required")
        self.assertEqual(self.s.state, "waiting")

    def test_page_mentions_saved_values(self):
        self.assertIn("already has a token", pairing.page("", has_token=True))
        self.assertIn("already saved", pairing.page("", has_sgdb_key=True))
        self.assertIn("steamgriddb.com/profile/preferences/api", pairing.page(""))

    def test_page_fields(self):
        page = pairing.page("http://gf.local:8080")
        for name in ("server_url", "token", "sgdb_key"):
            self.assertIn(f'name="{name}"', page)

    def test_html_escapes_server_url(self):
        self.assertNotIn("<script>alert", pairing.page('"><script>alert(1)</script>'))


if __name__ == "__main__":
    unittest.main()
