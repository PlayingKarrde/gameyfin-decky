"""Run: python3 -m unittest discover -s tests"""

import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))

from gameyfin import deps, selfupdate  # noqa: E402


def touch(root, rel, data=b"MZ"):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)


# Records how it was called: one line per call, "<verb> <args...>", plus the cwd.
FAKE_PROTON = """#!/bin/bash
echo "$PWD|$*" >>"$CALLS"
"""


class FindRedistsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.game = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_finds_and_orders_known_installers(self):
        touch(self.game, "game.exe")
        touch(self.game, "__redist/DirectX/DXSETUP.exe")
        touch(self.game, "__redist/MSVC2015/VC_redist.x64.exe")
        touch(self.game, "__redist/MSVC2008/vcredist_x86.exe")
        touch(self.game, "_CommonRedist/XNA/xnafx40_redist.msi")
        touch(self.game, "_CommonRedist/OpenAL/oalinst.exe")
        touch(self.game, "_CommonRedist/dotNet/NDP472-KB4054530-x86-x64-AllOS-ENU.exe")  # skipped: wine-mono
        found = deps.find_redists(self.game)
        labels = [r["label"] for r in found]
        self.assertEqual(labels[:2], ["Visual C++ 2008 x86", "Visual C++ 2015 x64"])
        self.assertEqual(labels[2], "DirectX")
        self.assertEqual(set(labels[3:]), {"XNA Framework", "OpenAL"})
        flags = {r["label"]: r["flags"] for r in found}
        self.assertEqual(flags["Visual C++ 2008 x86"], "/q")
        self.assertEqual(flags["Visual C++ 2015 x64"], "/q /norestart")

    def test_duplicates_listed_once(self):
        touch(self.game, "a/vc_redist.x64.exe", b"same")
        touch(self.game, "b/vc_redist.x64.exe", b"same")
        self.assertEqual(len(deps.find_redists(self.game)), 1)

    def test_no_wrapper_without_redists_or_with_unsafe_path(self):
        self.assertIsNone(deps.write_wrapper(self.game, []))
        bad = os.path.join(self.game, 'odd"name')
        touch(bad, "vc_redist.x64.exe")
        self.assertIsNone(deps.write_wrapper(bad, deps.find_redists(bad)))


class WrapperTests(unittest.TestCase):
    """Runs the generated run.sh the way Steam would, with a fake Proton."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.game = os.path.join(root, "My Game")
        self.prefix = os.path.join(root, "compatdata", "123")
        self.calls = os.path.join(root, "calls.txt")
        tool = os.path.join(root, "Proton - Experimental")
        os.makedirs(tool)
        self.proton = os.path.join(tool, "proton")
        with open(self.proton, "w") as f:
            f.write(FAKE_PROTON)
        os.chmod(self.proton, 0o755)
        touch(self.game, "game.exe")
        touch(self.game, "__redist/MSVC2019/VC_redist.x64.exe")
        touch(self.game, "_CommonRedist/XNA/xnafx40_redist.msi")
        self.wrapper = deps.write_wrapper(self.game, deps.find_redists(self.game))
        # Steam's reaper and launch wrapper: skip their own args up to "--", run the rest.
        self.reaper = self.passthrough("reaper")
        self.launch_wrapper = self.passthrough("steam-launch-wrapper")

    def passthrough(self, name, note=None):
        path = os.path.join(self.tmp.name, "steam", name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        echo = f'echo "{note}" >>"$CALLS"; ' if note else ""
        with open(path, "w") as f:
            f.write(f'#!/bin/bash\nwhile [ "$1" != "--" ]; do shift; done; shift; {echo}exec "$@"\n')
        os.chmod(path, 0o755)
        return path

    def tearDown(self):
        self.tmp.cleanup()

    def launch(self, *steam_cmd, prefix=True):
        env = dict(os.environ, CALLS=self.calls)
        if prefix:
            env["STEAM_COMPAT_DATA_PATH"] = self.prefix
        # Steam: /bin/bash "<wrapper>" %command%
        return subprocess.run(["/bin/bash", os.path.join(self.game, self.wrapper), *steam_cmd],
                              env=env, capture_output=True, text=True, timeout=30)

    def read_calls(self):
        if not os.path.exists(self.calls):
            return []
        with open(self.calls) as f:
            return [line.rstrip("\n").split("|", 1) for line in f]

    def test_runs_installers_once_then_the_game(self):
        steam = [self.reaper, "SteamLaunch", "AppId=123", "--", self.proton, "waitforexitandrun",
                 os.path.join(self.game, "game.exe"), "-arg"]
        self.launch(*steam)
        calls = self.read_calls()
        self.assertEqual(len(calls), 3)  # VC++, XNA (via msiexec), then the game itself
        cwd, args = calls[0]
        self.assertEqual(cwd, os.path.join(self.game, "__redist", "MSVC2019"))
        self.assertEqual(args, f"waitforexitandrun {self.game}/__redist/MSVC2019/VC_redist.x64.exe /q /norestart")
        self.assertTrue(calls[1][1].startswith("waitforexitandrun msiexec /i Z:\\"))
        self.assertTrue(calls[1][1].endswith("xnafx40_redist.msi /qn"))
        self.assertEqual(calls[2][1], f"waitforexitandrun {self.game}/game.exe -arg")
        # Second launch: only the game.
        os.remove(self.calls)
        self.launch(*steam)
        self.assertEqual([a for _, a in self.read_calls()], [f"waitforexitandrun {self.game}/game.exe -arg"])

    def test_reuses_runtime_entry_point_without_steam_wrappers(self):
        entry = self.passthrough("_v2-entry-point", note="entry")
        self.launch(self.reaper, "SteamLaunch", "AppId=123", "--", self.launch_wrapper, "--",
                    entry, "--verb=waitforexitandrun", "--", self.proton, "waitforexitandrun",
                    os.path.join(self.game, "game.exe"))
        with open(self.calls) as f:
            lines = f.read().splitlines()
        # Each installer and the game itself went through the runtime entry point.
        self.assertEqual([line for line in lines if line == "entry"], ["entry"] * 3)
        self.assertEqual(len(lines), 6)

    def test_native_or_no_prefix_just_runs_the_game(self):
        r = self.launch("/bin/echo", "hello", prefix=False)
        self.assertEqual(r.stdout.strip(), "hello")
        self.assertEqual(self.read_calls(), [])


class SelfUpdateTests(unittest.TestCase):
    def test_versions(self):
        self.assertTrue(selfupdate.is_newer("0.5.0", "0.4.0"))
        self.assertTrue(selfupdate.is_newer("v0.10", "0.9.9"))
        self.assertFalse(selfupdate.is_newer("0.4.0", "0.4"))
        self.assertFalse(selfupdate.is_newer("0.5.0-beta", "0.4.0"))  # unparsable: never nag

    def test_check_reads_release(self):
        release = {"tag_name": "v0.6.0", "html_url": "https://example/rel",
                   "assets": [{"name": "gameyfin-decky-0.6.0.zip", "browser_download_url": "https://example/z.zip",
                               "digest": "sha256:abc"}]}
        r = selfupdate.check("0.5.0", force=True, fetch=lambda: release)
        self.assertEqual((r["newer"], r["latest"], r["url"], r["sha256"]), (True, "0.6.0", "https://example/z.zip", "abc"))
        release["assets"] = []
        self.assertFalse(selfupdate.check("0.5.0", force=True, fetch=lambda: release)["newer"])


if __name__ == "__main__":
    unittest.main()
