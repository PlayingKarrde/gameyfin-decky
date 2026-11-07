"""Run: python3 -m unittest discover -s tests"""

import json
import os
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))

from gameyfin.installer import MARKER, Cancelled  # noqa: E402
from gameyfin.installers import (  # noqa: E402
    InstallerError, find_installer, install_from_installer, installer_parts)

# Stands in for innoextract: writes a GOG-like layout into --output-dir.
FAKE = f"""#!{sys.executable}
import os, sys, time
out = sys.argv[sys.argv.index("--output-dir") + 1]
mode = os.environ.get("FAKE_MODE", "ok")
if mode == "fail":
    print("Not a supported Inno Setup installer!"); sys.exit(1)
if mode == "slow":
    time.sleep(30)
for rel, data in {{"game.exe": b"MZ", "Engine/a.dll": b"x", "__redist/vc.exe": b"MZ",
                   "commonappdata/GOG.com/u.dll": b"x"}}.items():
    p = os.path.join(out, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
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

    def tearDown(self):
        os.environ.pop("FAKE_MODE", None)
        self.tmp.cleanup()

    def test_detection(self):
        setup = find_installer(self.game)
        self.assertEqual(os.path.basename(setup), self.setup)
        self.assertEqual(len(installer_parts(setup)), 3)
        touch(self.game, "game.exe")  # a real game next to a setup: not an installer download
        self.assertIsNone(find_installer(self.game))

    def test_unpacks_and_replaces_installer(self):
        n = install_from_installer(self.fake, self.game, find_installer(self.game), lambda *a: None, lambda: False)
        self.assertEqual(sorted(os.listdir(self.game)), sorted([MARKER, "Engine", "__redist", "game.exe"]))
        self.assertGreater(n, 0)

    def test_failure_keeps_installer(self):
        os.environ["FAKE_MODE"] = "fail"
        with self.assertRaises(InstallerError) as cm:
            install_from_installer(self.fake, self.game, find_installer(self.game), lambda *a: None, lambda: False)
        self.assertIn("Not a supported", str(cm.exception))
        self.assertIn(self.setup, os.listdir(self.game))
        self.assertNotIn(".gameyfin-installer", os.listdir(self.game))

    def test_clash_keeps_installer(self):
        os.makedirs(os.path.join(self.game, "Engine"))
        with self.assertRaises(InstallerError):
            install_from_installer(self.fake, self.game, find_installer(self.game), lambda *a: None, lambda: False)
        self.assertIn(self.setup, os.listdir(self.game))

    def test_cancel_kills_extractor(self):
        os.environ["FAKE_MODE"] = "slow"
        with self.assertRaises(Cancelled):
            install_from_installer(self.fake, self.game, find_installer(self.game), lambda *a: None, lambda: True)
        self.assertIn(self.setup, os.listdir(self.game))

    def test_runs_without_exec_bit_via_loader(self):
        from gameyfin.installers import innoextract_cmd
        os.chmod(self.fake, stat.S_IRUSR | stat.S_IWUSR)
        cmd = innoextract_cmd(self.fake)
        self.assertEqual(cmd[-1], self.fake)
        self.assertEqual(len(cmd), 2)


if __name__ == "__main__":
    unittest.main()
