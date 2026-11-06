"""On-disk cache for Gameyfin images.

Gameyfin images need the API key, so the Steam UI can't load them directly,
and many covers are >1 MB PNGs, beyond Decky's ~1 MiB bridge cap. Flow:

1. ``describe(url)``: if a thumbnail exists, return it inline. Otherwise
   download the original to disk and report its size and chunk count.
2. ``chunk(url, i)``: the original in base64 slices the bridge can carry.
3. The frontend downscales on a canvas and calls ``save_thumbnail``, so the
   next request returns a ~30 KB JPEG immediately.
"""

from __future__ import annotations

import base64
import os
import re
import threading

from .client import GameyfinClient, GameyfinError

# Multiple of 3 so per-chunk base64 strings concatenate into valid base64.
CHUNK_BYTES = 384 * 1024
MAX_THUMB_BYTES = 256 * 1024

_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}
_SAFE = re.compile(r"[^A-Za-z0-9_-]")
_THUMB_PREFIX = "data:image/jpeg;base64,"


class ImageCache:
    def __init__(self, directory: str):
        self.orig_dir = os.path.join(directory, "images", "orig")
        self.thumb_dir = os.path.join(directory, "images", "thumb")

    @staticmethod
    def _key(image_url: str) -> str:
        return _SAFE.sub("_", image_url.strip("/"))

    def _thumb_path(self, url: str) -> str:
        return os.path.join(self.thumb_dir, self._key(url) + ".jpg")

    def _find_orig(self, url: str) -> tuple[str, str] | None:
        key = self._key(url)
        for ctype, ext in _EXT.items():
            p = os.path.join(self.orig_dir, f"{key}.{ext}")
            if os.path.exists(p):
                return p, ctype
        return None

    @staticmethod
    def _write_atomic(path: str, data: bytes) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Unique tmp: the grid and the artwork step can fetch the same image concurrently.
        tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)

    def _ensure_orig(self, client: GameyfinClient, url: str) -> tuple[str, str]:
        hit = self._find_orig(url)
        if hit:
            return hit
        img = client.fetch_image(url)
        ext = _EXT.get(img.content_type)
        if not ext:
            raise GameyfinError(f"Unsupported image type {img.content_type}", code="bad_image")
        path = os.path.join(self.orig_dir, f"{self._key(url)}.{ext}")
        self._write_atomic(path, img.data)
        return path, img.content_type

    def describe(self, client: GameyfinClient, url: str) -> dict:
        tp = self._thumb_path(url)
        if os.path.exists(tp):
            with open(tp, "rb") as f:
                return {"thumb": _THUMB_PREFIX + base64.b64encode(f.read()).decode("ascii")}
        path, ctype = self._ensure_orig(client, url)
        size = os.path.getsize(path)
        return {"content_type": ctype, "size": size, "chunks": max(1, -(-size // CHUNK_BYTES))}

    def describe_original(self, client: GameyfinClient, url: str) -> dict:
        """Full-size image (for Steam artwork), never the thumbnail."""
        path, ctype = self._ensure_orig(client, url)
        size = os.path.getsize(path)
        return {"content_type": ctype, "size": size, "chunks": max(1, -(-size // CHUNK_BYTES))}

    def chunk(self, url: str, index: int) -> str:
        hit = self._find_orig(url)
        if not hit:
            raise GameyfinError("Image not cached; call get_image first", code="not_cached")
        with open(hit[0], "rb") as f:
            f.seek(int(index) * CHUNK_BYTES)
            return base64.b64encode(f.read(CHUNK_BYTES)).decode("ascii")

    def save_thumbnail(self, url: str, data_url: str) -> None:
        if not data_url.startswith(_THUMB_PREFIX):
            raise GameyfinError("Thumbnail must be a JPEG data URL", code="bad_thumb")
        data = base64.b64decode(data_url[len(_THUMB_PREFIX):], validate=True)
        if len(data) > MAX_THUMB_BYTES or data[:3] != b"\xff\xd8\xff":
            raise GameyfinError("Invalid thumbnail", code="bad_thumb")
        self._write_atomic(self._thumb_path(url), data)
        # The original is no longer needed for the grid.
        hit = self._find_orig(url)
        if hit:
            os.remove(hit[0])
