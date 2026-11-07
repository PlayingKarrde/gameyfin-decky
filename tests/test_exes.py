import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))

from gameyfin.client import GameyfinError  # noqa: E402
from gameyfin.exes import (  # noqa: E402
    ensure_executable, find_executables, gog_play_task, is_ambiguous, preferred_kind, restore_exec_bits)
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


def write(root, rel, data: bytes):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)
    return p


class NativeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_unity_linux_build(self):
        write(self.d, "MyGame.x86_64", b"\x7fELF" + b"\0" * 5000)
        write(self.d, "UnityPlayer.so", b"\x7fELF" + b"\0" * 9000)
        write(self.d, "MyGame_Data/level0", b"data")
        c = find_executables(self.d, "My Game")
        self.assertEqual([(x["path"], x["kind"]) for x in c], [("MyGame.x86_64", "linux")])
        self.assertFalse(is_ambiguous(c))

    def test_gog_start_sh_and_extensionless_elf(self):
        write(self.d, "start.sh", b"#!/bin/bash\n")
        write(self.d, "game/runner", b"\x7fELF" + b"\0" * 100)
        write(self.d, "game/readme", b"text")
        c = find_executables(self.d, "Something")
        self.assertEqual(c[0]["path"], "start.sh")
        self.assertIn("game/runner", [x["path"] for x in c])
        self.assertNotIn("game/readme", [x["path"] for x in c])

    def test_kind_preference(self):
        write(self.d, "Game.exe", b"MZ")
        write(self.d, "Game.x86_64", b"\x7fELF")
        self.assertEqual(find_executables(self.d, "Game")[0]["kind"], "windows")
        self.assertEqual(find_executables(self.d, "Game", prefer="linux")[0]["kind"], "linux")
        # One of each kind is not ambiguous: the other kind isn't competing.
        self.assertFalse(is_ambiguous(find_executables(self.d, "Game")))
        self.assertEqual(preferred_kind(["LINUX"]), "linux")
        self.assertEqual(preferred_kind(["PC_MICROSOFT_WINDOWS"]), "windows")
        self.assertIsNone(preferred_kind(["LINUX", "PC_MICROSOFT_WINDOWS"]))
        self.assertIsNone(preferred_kind([]))

    def test_restore_exec_bits(self):
        elf = write(self.d, "bin/game", b"\x7fELF")
        sh = write(self.d, "start.sh", b"#!/bin/sh\n")
        data = write(self.d, "data.pak", b"PAK")
        for p in (elf, sh, data):
            os.chmod(p, 0o644)
        self.assertEqual(restore_exec_bits(self.d), 2)
        self.assertTrue(os.access(elf, os.X_OK) and os.access(sh, os.X_OK))
        self.assertFalse(os.access(data, os.X_OK))

    def test_ensure_executable_stays_inside(self):
        outside = write(self.d, "outside.sh", b"#!/bin/sh")
        os.chmod(outside, 0o644)
        os.makedirs(os.path.join(self.d, "game"))
        ensure_executable(os.path.join(self.d, "game"), "../outside.sh")
        self.assertFalse(os.access(outside, os.X_OK))


class GogTests(unittest.TestCase):
    def test_play_task(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "DOSBOX/dosbox.exe", b"MZ")
            info = {"playTasks": [
                {"type": "FileTask", "path": "readme.txt", "isPrimary": False},
                {"type": "FileTask", "isPrimary": True, "path": "DOSBOX\\dosbox.exe",
                 "arguments": "-conf \"..\\game.conf\" -c exit", "workingDir": "DOSBOX"},
            ]}
            write(d, "goggame-123.info", json.dumps(info).encode())
            t = gog_play_task(d)
            self.assertEqual(t["path"], "DOSBOX/dosbox.exe")
            self.assertEqual(t["work_dir"], "DOSBOX")
            self.assertIn("-conf", t["args"])

    def test_play_task_must_stay_inside(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "game/x", b"")
            info = {"playTasks": [{"type": "FileTask", "isPrimary": True, "path": "../../etc/passwd"}]}
            write(d, "game/goggame-1.info", json.dumps(info).encode())
            self.assertIsNone(gog_play_task(os.path.join(d, "game")))
            self.assertIsNone(gog_play_task(os.path.join(d, "missing")))


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
