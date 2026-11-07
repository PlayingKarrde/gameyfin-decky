"""Run: python3 -m unittest discover -s tests"""

import json
import os
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))

from gameyfin.installer import MARKER, Cancelled  # noqa: E402
from gameyfin.exes import find_executables, gog_play_task  # noqa: E402
from gameyfin.installers import (  # noqa: E402
    InstallerError, find_installers, install_from_installers, installer_parts)

# Stands in for innoextract: writes a GOG-like layout into --output-dir. Installers with
# "dlc" in the name produce a DLC (its own goggame info, an overwritten base file).
FAKE = f"""#!{sys.executable}
import json, os, sys, time
out = sys.argv[sys.argv.index("--output-dir") + 1]
setup = os.path.basename(sys.argv[-1])
mode = os.environ.get("FAKE_MODE", "ok")
if mode == "fail" or (os.environ.get("FAKE_FAIL") or "<none>") in setup:
    print("Not a supported Inno Setup installer!"); sys.exit(1)
if mode == "slow":
    time.sleep(30)
if "dlc" in setup:
    files = {{"goggame-2.info": json.dumps({{"gameId": "2", "rootGameId": "1"}}).encode(),
              "DLC/dlc.pak": b"d", "Engine/a.dll": b"dlc"}}
else:
    task = {{"isPrimary": True, "type": "FileTask", "path": "game.exe"}}
    files = {{"game.exe": b"MZ", "Engine/a.dll": b"x", "Engine/b.dll": b"x", "__redist/vc.exe": b"MZ",
              "commonappdata/GOG.com/u.dll": b"x",
              "goggame-1.info": json.dumps({{"gameId": "1", "rootGameId": "1", "playTasks": [task]}}).encode()}}
for rel, data in files.items():
    p = os.path.join(out, rel); os.makedirs(os.path.dirname(p) or out, exist_ok=True)
    open(p, "wb").write(data)
"""


def touch(d, name, data=b"x"):
    with open(os.path.join(d, name), "wb") as f:
        f.write(data)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.fake = os.path.join(self.root, "innoextract")
        with open(self.fake, "w") as f:
            f.write(FAKE)
        os.chmod(self.fake, 0o755)
        self.game = os.path.join(self.root, "Game")
        os.makedirs(self.game)
        self.setup = "setup_game_1.0_(123).exe"
        for n in (self.setup, "setup_game_1.0_(123)-1.bin", "setup_game_1.0_(123)-2.bin"):
            touch(self.game, n)
        with open(os.path.join(self.game, MARKER), "w") as f:
            json.dump({"game_id": "1"}, f)
        os.environ.pop("FAKE_MODE", None)
        os.environ.pop("FAKE_FAIL", None)

    def tearDown(self):
        os.environ.pop("FAKE_MODE", None)
        os.environ.pop("FAKE_FAIL", None)
        self.tmp.cleanup()

    def run_install(self):
        return install_from_installers(self.fake, self.game, find_installers(self.game), lambda *a: None,
                                       lambda: False)

    def add_dlc(self, size=1):
        # Same stem prefix as the base game: its parts must not be mistaken for the base's.
        dlc = "setup_game_1.0_(123)_dlc_1.0_(124)"
        touch(self.game, dlc + ".exe", b"x" * size)
        touch(self.game, dlc + "-1.bin", b"x" * size)
        return dlc

    def test_detection(self):
        setups = find_installers(self.game)
        self.assertEqual([os.path.basename(s) for s in setups], [self.setup])
        self.assertEqual(len(installer_parts(setups[0])), 3)
        touch(self.game, "game.exe")  # a real game next to a setup: not an installer download
        self.assertEqual(find_installers(self.game), [])

    def test_detection_with_dlc_and_patch(self):
        dlc = self.add_dlc()
        touch(self.game, "patch_game_0.9_to_1.0.exe")  # doesn't make it "a game folder"
        setups = [os.path.basename(s) for s in find_installers(self.game)]
        self.assertEqual(sorted(setups), sorted([self.setup, dlc + ".exe"]))
        base_parts = [os.path.basename(p) for p in installer_parts(os.path.join(self.game, self.setup))]
        self.assertNotIn(dlc + "-1.bin", base_parts)

    def test_unpacks_and_replaces_installer(self):
        res = self.run_install()
        self.assertEqual(sorted(os.listdir(self.game)),
                         sorted([MARKER, "Engine", "__redist", "game.exe", "goggame-1.info"]))
        self.assertGreater(res.installed_bytes, 0)
        self.assertEqual((res.dlc, res.warnings), (0, []))

    def test_dlc_layered_on_base(self):
        self.add_dlc(size=10_000)  # bigger than the base: the GOG info, not size, picks the base
        res = self.run_install()
        names = os.listdir(self.game)
        self.assertEqual(res.dlc, 1)
        self.assertFalse([n for n in names if n.endswith((".exe", ".bin")) and n != "game.exe"])
        with open(os.path.join(self.game, "Engine", "a.dll"), "rb") as f:
            self.assertEqual(f.read(), b"dlc")  # DLC replaced the base file...
        self.assertTrue(os.path.isfile(os.path.join(self.game, "Engine", "b.dll")))  # ...and kept the rest
        self.assertTrue(os.path.isfile(os.path.join(self.game, "DLC", "dlc.pak")))
        self.assertEqual(gog_play_task(self.game)["path"], "game.exe")  # base info wins over the DLC's

    def test_failed_dlc_is_a_warning(self):
        dlc = self.add_dlc()
        os.environ["FAKE_FAIL"] = "dlc"
        res = self.run_install()
        self.assertEqual(res.dlc, 0)
        self.assertEqual(len(res.warnings), 1)
        self.assertIn(dlc + ".exe", os.listdir(self.game))  # kept for the user
        self.assertIn("game.exe", os.listdir(self.game))
        self.assertEqual(find_executables(self.game)[0]["path"], "game.exe")

    def test_failed_base_fails_install(self):
        self.add_dlc()
        os.environ["FAKE_FAIL"] = "(123).exe"
        with self.assertRaises(InstallerError):
            self.run_install()
        self.assertIn(self.setup, os.listdir(self.game))
        self.assertNotIn("DLC", os.listdir(self.game))

    def test_patch_left_with_warning_and_not_a_candidate(self):
        touch(self.game, "patch_game_0.9_to_1.0.exe", b"MZ")
        res = self.run_install()
        self.assertEqual(len(res.warnings), 1)
        self.assertNotIn("patch_game_0.9_to_1.0.exe", [c["path"] for c in find_executables(self.game)])

    def test_failure_keeps_installer(self):
        os.environ["FAKE_MODE"] = "fail"
        with self.assertRaises(InstallerError) as cm:
            self.run_install()
        self.assertIn("Not a supported", str(cm.exception))
        self.assertIn(self.setup, os.listdir(self.game))
        self.assertNotIn(".gameyfin-installer", os.listdir(self.game))

    def test_clash_keeps_installer(self):
        os.makedirs(os.path.join(self.game, "Engine"))
        with self.assertRaises(InstallerError):
            self.run_install()
        self.assertIn(self.setup, os.listdir(self.game))

    def test_cancel_kills_extractor(self):
        os.environ["FAKE_MODE"] = "slow"
        with self.assertRaises(Cancelled):
            install_from_installers(self.fake, self.game, find_installers(self.game), lambda *a: None,
                                    lambda: True)
        self.assertIn(self.setup, os.listdir(self.game))

    def test_runs_without_exec_bit_via_loader(self):
        from gameyfin.installers import innoextract_cmd
        os.chmod(self.fake, stat.S_IRUSR | stat.S_IWUSR)
        cmd = innoextract_cmd(self.fake)
        self.assertEqual(cmd[-1], self.fake)
        self.assertEqual(len(cmd), 2)


if __name__ == "__main__":
    unittest.main()
