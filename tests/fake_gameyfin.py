#!/usr/bin/env python3
"""Tiny fake Gameyfin server for exercising the download worker end-to-end.

  python3 tests/fake_gameyfin.py [--port 8099] [--mb 200] [--rate-mbps 400]

Serves game id "1" as a STORED zip with data descriptors (like Gameyfin's
directdownload plugin), throttled so progress is observable. Accepts any key.
"""

import argparse
import io
import json
import os
import tempfile
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PROVIDER = "org.example.Fake$Provider"


class _Unseekable(io.RawIOBase):
    def __init__(self, f):
        self.f = f

    def writable(self):
        return True

    def write(self, b):
        return self.f.write(b)


def build_zip(mb: int) -> str:
    path = os.path.join(tempfile.gettempdir(), f"fake-gameyfin-{mb}mb.zip")
    if os.path.exists(path):
        return path
    block = os.urandom(1024 * 1024)
    with open(path, "wb") as raw, zipfile.ZipFile(_Unseekable(raw), "w", zipfile.ZIP_STORED) as zf:
        for name, size in [("FakeGame.exe", 2), ("UnityCrashHandler64.exe", 1), ("FakeGame_Data/data.pak", mb - 3)]:
            with zf.open(zipfile.ZipInfo(name), "w") as w:
                for _ in range(max(size, 0)):
                    w.write(block)
    return path


def make_handler(zip_path: str, rate: float, v1_bug: bool = False, public: bool = True):
    size = os.path.getsize(zip_path)
    game = {"id": "1", "title": "Fake Game: Test Edition", "fileSize": size, "platforms": [], "images": []}

    class H(BaseHTTPRequestHandler):
        def _json(self, obj, status=200):
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            p = self.path.split("?")[0]
            if p == "/v1/download-providers":
                return self._json([{"id": PROVIDER, "name": "Fake", "description": "", "priority": 1}])
            if p == "/v1/games/1":
                return self._json(game)
            if p == "/v1/games/1/download" and v1_bug:
                # Gameyfin 2.6.0: 500 problem+json that keeps the zip's Content-Length.
                body = json.dumps({"detail": "The request could not be completed", "status": 500,
                                   "code": "request_failed"}).encode()
                self.send_response(500)
                self.send_header("Content-Type", "application/problem+json")
                self.send_header("Content-Length", str(size))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)
                self.close_connection = True
                return
            if p == "/download/1" and not public:
                body = b"<html>login</html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if p in ("/v1/games/1/download", "/download/1"):
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(size))
                self.send_header("Content-Disposition", 'attachment; filename="Fake Game Test Edition.zip"')
                self.end_headers()
                chunk = 256 * 1024
                with open(zip_path, "rb") as f:
                    t0, sent = time.monotonic(), 0
                    while buf := f.read(chunk):
                        try:
                            self.wfile.write(buf)
                        except (BrokenPipeError, ConnectionResetError):
                            return
                        sent += len(buf)
                        ahead = sent / rate - (time.monotonic() - t0)
                        if ahead > 0:
                            time.sleep(ahead)
                return
            self._json({"title": "Not Found", "status": 404}, 404)

        def log_message(self, *a):
            pass

    return H


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--mb", type=int, default=200)
    ap.add_argument("--rate-mbps", type=float, default=400, help="megabits/s")
    ap.add_argument("--v1-bug", action="store_true", help="emulate Gameyfin 2.6.0's broken /v1 download")
    ap.add_argument("--no-public", action="store_true", help="web /download needs a login")
    a = ap.parse_args()
    z = build_zip(a.mb)
    print(f"fake gameyfin on :{a.port}, zip {os.path.getsize(z)} bytes", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(z, a.rate_mbps * 125_000, a.v1_bug, not a.no_public)).serve_forever()
