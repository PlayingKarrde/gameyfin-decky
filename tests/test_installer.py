"""Run: python3 -m unittest discover -s tests"""

import io
import json
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))

from gameyfin import installer, jobs  # noqa: E402
from gameyfin.client import GameyfinError  # noqa: E402


class _Unseekable(io.RawIOBase):
    """Forces zipfile to emit data descriptors, like Gameyfin's streamed zips."""

    def __init__(self, f):
        self.f = f

    def writable(self):
        return True

    def write(self, b):
        return self.f.write(b)


def make_stored_zip(path, files: dict[str, bytes]):
    with open(path, "wb") as raw, zipfile.ZipFile(_Unseekable(raw), "w", zipfile.ZIP_STORED) as zf:
        for name, data in files.items():
            with zf.open(zipfile.ZipInfo(name), "w") as w:
                w.write(data)


def noop(*_):
    pass


class ExtractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_stored_zip_with_data_descriptors(self):
        z = os.path.join(self.d, "g.zip")
        make_stored_zip(z, {"Game.exe": b"MZ" + b"x" * 5000, "data/level1.pak": b"y" * 70000})
        with zipfile.ZipFile(z) as zf:
            self.assertTrue(all(i.flag_bits & 0x08 for i in zf.infolist()), "expected data descriptors")
        out = os.path.join(self.d, "out")
        n = installer.extract_zip(z, out, noop, lambda: False)
        self.assertEqual(n, 75002)
        self.assertEqual(open(os.path.join(out, "data/level1.pak"), "rb").read(), b"y" * 70000)

    def test_strips_single_top_level_folder(self):
        z = os.path.join(self.d, "g.zip")
        make_stored_zip(z, {"MyGame/Game.exe": b"a", "MyGame/sub/x.dll": b"b"})
        out = os.path.join(self.d, "out")
        installer.extract_zip(z, out, noop, lambda: False)
        self.assertTrue(os.path.exists(os.path.join(out, "Game.exe")))
        self.assertTrue(os.path.exists(os.path.join(out, "sub/x.dll")))

    def test_keeps_multiple_top_level_entries(self):
        z = os.path.join(self.d, "g.zip")
        make_stored_zip(z, {"a/Game.exe": b"a", "readme.txt": b"b"})
        out = os.path.join(self.d, "out")
        installer.extract_zip(z, out, noop, lambda: False)
        self.assertTrue(os.path.exists(os.path.join(out, "a/Game.exe")))

    def test_rejects_zip_slip(self):
        for bad in ("../evil.txt", "/etc/evil", "a/../../evil", "C:/evil"):
            z = os.path.join(self.d, "bad.zip")
            make_stored_zip(z, {bad: b"x"})
            with self.assertRaises(GameyfinError, msg=bad):
                installer.extract_zip(z, os.path.join(self.d, "out"), noop, lambda: False)
        self.assertFalse(os.path.exists(os.path.join(self.d, "evil.txt")))

    def test_cancel_during_extract(self):
        z = os.path.join(self.d, "g.zip")
        make_stored_zip(z, {"big.bin": b"z" * (3 * installer.CHUNK)})
        with self.assertRaises(installer.Cancelled):
            installer.extract_zip(z, os.path.join(self.d, "out"), noop, lambda: True)


class NamingTests(unittest.TestCase):
    def test_safe_dirname(self):
        self.assertEqual(installer.safe_dirname('Halo: Reach / "GOTY"?'), "Halo Reach GOTY")
        self.assertEqual(installer.safe_dirname("  ...  "), "game")
        self.assertEqual(installer.safe_dirname("Horizon Zero Dawn™ Remastered"), "Horizon Zero Dawn™ Remastered")

    def test_choose_install_dir_collision(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "Foo"))
            self.assertEqual(installer.choose_install_dir(d, "Foo", "7"), os.path.join(d, "Foo [gameyfin-7]"))
            with open(os.path.join(d, "Foo", installer.MARKER), "w") as f:
                json.dump({"game_id": "7"}, f)
            self.assertEqual(installer.choose_install_dir(d, "Foo", "7"), os.path.join(d, "Foo"))

    def test_content_disposition(self):
        f = installer._filename_from_disposition
        self.assertEqual(f('attachment; filename="Game.exe"'), "Game.exe")
        self.assertEqual(f("attachment; filename*=UTF-8''Pok%C3%A9mon.zip"), "Pokémon.zip")
        self.assertEqual(f('attachment; filename="../../x.exe"'), "x.exe")
        self.assertIsNone(f(None))


class FakeResp:
    def __init__(self, body: bytes, headers: dict):
        self._b = io.BytesIO(body)
        from email.message import Message

        self.headers = Message()
        for k, v in headers.items():
            self.headers[k] = v

    def read(self, n=-1):
        return self._b.read(n)

    def close(self):
        pass


class FakeClient:
    def __init__(self, body, headers):
        self.body, self.headers = body, headers

    def download_providers(self):
        return [{"id": "prov"}]

    def open_download(self, game_id, provider):
        return FakeResp(self.body, self.headers)


class InstallTests(unittest.TestCase):
    def _zip_bytes(self, files):
        with tempfile.NamedTemporaryFile(delete=False) as t:
            path = t.name
        make_stored_zip(path, files)
        data = open(path, "rb").read()
        os.remove(path)
        return data

    def test_full_install_zip(self):
        body = self._zip_bytes({"Game.exe": b"MZ", "data.pak": b"p" * 100})
        c = FakeClient(body, {"Content-Type": "application/octet-stream", "Content-Length": str(len(body)),
                              "Content-Disposition": 'attachment; filename="My Game.zip"'})
        with tempfile.TemporaryDirectory() as d:
            res = installer.install(c, {"id": 5, "title": "My: Game", "fileSize": 102}, d, "job1", noop,
                                    lambda: False)
            self.assertEqual(res.install_dir, os.path.join(d, "My Game"))
            self.assertEqual(sorted(os.listdir(res.install_dir)), [".gameyfin.json", "Game.exe", "data.pak"])
            self.assertEqual(os.listdir(d), ["My Game"], "temp dir and archive must be cleaned up")

    def test_raw_single_file(self):
        c = FakeClient(b"MZsingle", {"Content-Type": "application/octet-stream", "Content-Length": "8",
                                     "Content-Disposition": 'attachment; filename="Tiny.exe"'})
        with tempfile.TemporaryDirectory() as d:
            res = installer.install(c, {"id": 6, "title": "Tiny", "fileSize": 8}, d, "j", noop, lambda: False)
            self.assertTrue(os.path.exists(os.path.join(res.install_dir, "Tiny.exe")))

    def test_truncated_download_cleans_up(self):
        c = FakeClient(b"PK\x03\x04short", {"Content-Type": "application/octet-stream", "Content-Length": "999"})
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(GameyfinError) as cm:
                installer.install(c, {"id": 7, "title": "T", "fileSize": 999}, d, "j", noop, lambda: False)
            self.assertEqual(cm.exception.code, "truncated")
            self.assertEqual(os.listdir(d), [])

    def test_no_space(self):
        c = FakeClient(b"", {})
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(GameyfinError) as cm:
                installer.install(c, {"id": 8, "title": "Huge", "fileSize": 10**15}, d, "j", noop, lambda: False)
            self.assertEqual(cm.exception.code, "no_space")


class JobTests(unittest.TestCase):
    def test_job_roundtrip_and_cancel(self):
        with tempfile.TemporaryDirectory() as root:
            jd = jobs.create_job(root, {"game_id": "2", "title": "AM2R", "dest_root": "/x"})
            self.assertEqual(jobs.read_spec(jd)["game_id"], "2")
            self.assertEqual(oct(os.stat(os.path.join(jd, "job.json")).st_mode & 0o777), "0o600")
            self.assertEqual(jobs.list_jobs(root)[0]["phase"], "queued")
            self.assertFalse(jobs.cancel_requested(jd))
            jobs.request_cancel(jd)
            self.assertTrue(jobs.cancel_requested(jd))

    def test_dead_worker_detected(self):
        with tempfile.TemporaryDirectory() as root:
            jd = jobs.create_job(root, {"game_id": "2"})
            jobs.write_state(jd, {"job_id": "x", "phase": "downloading", "pid": 2**22 + 12345})
            import time

            st = json.load(open(os.path.join(jd, "state.json")))
            st["updated_at"] = time.time() - 10
            with open(os.path.join(jd, "state.json"), "w") as f:
                json.dump(st, f)
            self.assertEqual(jobs.read_state(jd)["phase"], "error")


if __name__ == "__main__":
    unittest.main()


class V1BugFallbackTests(unittest.TestCase):
    """GameyfinClient.open_download falls back to /download/{id} on Gameyfin 2.6.0's /v1 500."""

    def _serve(self, public):
        import threading
        from http.server import ThreadingHTTPServer
        sys.path.insert(0, os.path.dirname(__file__))
        import fake_gameyfin
        self.tmp = tempfile.TemporaryDirectory()
        z = os.path.join(self.tmp.name, "g.zip")
        make_stored_zip(z, {"G/Game.exe": b"MZ" + b"x" * 1000})
        srv = ThreadingHTTPServer(("127.0.0.1", 0), fake_gameyfin.make_handler(z, 1e12, v1_bug=True, public=public))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        self.addCleanup(self.tmp.cleanup)
        from gameyfin.client import GameyfinClient
        return GameyfinClient(f"http://127.0.0.1:{srv.server_address[1]}", "k"), z

    def test_falls_back_to_web_download(self):
        c, z = self._serve(public=True)
        with c.open_download("1", "p") as r, open(z, "rb") as f:
            self.assertEqual(r.read(), f.read())

    def test_clear_error_when_not_public(self):
        c, _ = self._serve(public=False)
        with self.assertRaises(GameyfinError) as cm:
            c.open_download("1", "p")
        self.assertEqual(cm.exception.code, "server_download_bug")
