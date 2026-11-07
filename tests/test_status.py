"""Run: python3 -m unittest discover -s tests"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))
sys.path.insert(0, os.path.dirname(__file__))

from gameyfin import installer  # noqa: E402
from gameyfin.client import GameyfinError  # noqa: E402
from gameyfin.status import check_all, check_one, files_state  # noqa: E402
import test_installer as ti  # noqa: E402  (module import: don't re-collect its TestCases)


def make_install(root, name, game_id):
    d = os.path.join(root, name)
    os.makedirs(d)
    with open(os.path.join(d, installer.MARKER), "w") as f:
        json.dump({"game_id": str(game_id)}, f)
    return d


class StatusTests(unittest.TestCase):
    def test_files_state(self):
        with tempfile.TemporaryDirectory() as d:
            ok = make_install(d, "A", 1)
            self.assertEqual(files_state(ok, "1"), "ok")
            self.assertEqual(files_state(ok, "2"), "unmarked")
            self.assertEqual(files_state(os.path.join(d, "gone"), "1"), "missing")
            self.assertEqual(files_state(None, "1"), "missing")

    def test_update_detection_uses_file_size(self):
        with tempfile.TemporaryDirectory() as d:
            inst = make_install(d, "A", 1)
            rec = {"game_id": "1", "install_dir": inst, "size": 100}
            same = check_one(lambda gid: {"id": gid, "title": "A", "fileSize": 100}, rec)
            self.assertFalse(same["update_available"])
            changed = check_one(lambda gid: {"id": gid, "title": "A", "fileSize": 120}, rec)
            self.assertTrue(changed["update_available"])
            # Newer records store the server size explicitly; it wins over installed size.
            rec2 = {**rec, "server_file_size": 120}
            self.assertFalse(check_one(lambda gid: {"id": gid, "fileSize": 120}, rec2)["update_available"])

    def test_missing_on_server_and_offline(self):
        rec = {"game_id": "5", "install_dir": "/nope", "title": "Gone", "size": 1}

        def not_found(_):
            raise GameyfinError("Not found", status=404)

        def offline(_):
            raise GameyfinError("Can't reach server", code="unreachable")

        r = check_one(not_found, rec)
        self.assertTrue(r["server_missing"])
        self.assertEqual(r["summary"]["title"], "Gone")
        r = check_one(offline, rec)
        self.assertFalse(r["server_missing"])
        self.assertIsNotNone(r["error"])
        self.assertEqual(check_all(None, [rec])[0]["files"], "missing")


class UpdateInPlaceTests(unittest.TestCase):
    def test_update_replaces_renamed_folder(self):
        """The server renamed the game; the update must land in the old folder, not a new one."""
        body = ti.InstallTests._zip_bytes(None, {"Game.exe": b"MZ2"})
        hdrs = {"Content-Type": "application/octet-stream", "Content-Length": str(len(body))}
        with tempfile.TemporaryDirectory() as d:
            old = make_install(d, "Old Name", 3)
            with open(os.path.join(old, "stale.txt"), "w") as f:
                f.write("x")
            res = installer.install(ti.FakeClient(body, hdrs), {"id": 3, "title": "New Name", "fileSize": len(body)},
                                    d, "j", ti.noop, lambda: False, install_dir=old)
            self.assertEqual(res.install_dir, old)
            self.assertEqual(sorted(os.listdir(old)), [".gameyfin.json", "Game.exe"])
            self.assertFalse(os.path.exists(os.path.join(d, "New Name")))

    def test_update_never_overwrites_foreign_folder(self):
        body = ti.InstallTests._zip_bytes(None, {"Game.exe": b"MZ"})
        hdrs = {"Content-Type": "application/octet-stream", "Content-Length": str(len(body))}
        with tempfile.TemporaryDirectory() as d:
            foreign = make_install(d, "Shared", 99)
            res = installer.install(ti.FakeClient(body, hdrs), {"id": 4, "title": "Mine", "fileSize": len(body)},
                                    d, "j", ti.noop, lambda: False, install_dir=foreign)
            self.assertNotEqual(res.install_dir, foreign)
            self.assertTrue(os.path.exists(os.path.join(foreign, installer.MARKER)))


if __name__ == "__main__":
    unittest.main()
