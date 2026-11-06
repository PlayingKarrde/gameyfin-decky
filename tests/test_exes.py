import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))

from gameyfin.client import GameyfinError  # noqa: E402
from gameyfin.exes import find_executables, is_ambiguous  # noqa: E402
from gameyfin.installed import InstalledStore, delete_game_dir  # noqa: E402


def touch(root, rel, size=1):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(b"\0" * size)


class ExeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_excludes_helpers_and_prefers_name_match(self):
        touch(self.d, "FakeGame.exe", 1000)
        touch(self.d, "UnityCrashHandler64.exe", 5000)
        touch(self.d, "Big Tool.exe", 9000)
        touch(self.d, "_CommonRedist/vcredist/vc_redist.x64.exe", 9000)
        c = find_executables(self.d, "Fake Game")
        self.assertEqual([x["path"] for x in c], ["FakeGame.exe", "Big Tool.exe"])
        self.assertFalse(is_ambiguous(c))

    def test_ambiguous_without_clear_winner(self):
        touch(self.d, "a.exe", 1000)
        touch(self.d, "b.exe", 900)
        self.assertTrue(is_ambiguous(find_executables(self.d, "Something Else")))

    def test_single_candidate(self):
        touch(self.d, "sub/run.exe", 10)
        c = find_executables(self.d, "X")
        self.assertEqual(c[0]["path"], "sub/run.exe")
        self.assertFalse(is_ambiguous(c))


class InstalledTests(unittest.TestCase):
    def test_store_and_safe_delete(self):
        with tempfile.TemporaryDirectory() as d:
            s = InstalledStore(d)
            s.put("7", {"title": "T", "install_dir": os.path.join(d, "T")})
            self.assertEqual(s.get("7")["title"], "T")
            g = os.path.join(d, "T")
            touch(g, "x.exe")
            with self.assertRaises(GameyfinError):
                delete_game_dir(g, "7")  # no marker
            with open(os.path.join(g, ".gameyfin.json"), "w") as f:
                json.dump({"game_id": "8"}, f)
            with self.assertRaises(GameyfinError):
                delete_game_dir(g, "7")  # wrong game
            with open(os.path.join(g, ".gameyfin.json"), "w") as f:
                json.dump({"game_id": "7"}, f)
            delete_game_dir(g, "7")
            self.assertFalse(os.path.exists(g))
            s.remove("7")
            self.assertIsNone(s.get("7"))


if __name__ == "__main__":
    unittest.main()
