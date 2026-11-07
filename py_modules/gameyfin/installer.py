"""Download + extract a Gameyfin game into a folder. Stdlib only.

Gameyfin streams folders as a STORED zip with data descriptors and no Range
support, so we write the whole archive to disk (same filesystem as the target),
then extract with random access via ``zipfile``. Single-file games arrive raw.
"""

from __future__ import annotations

import email.message
import http.client
import json
import os
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from typing import Callable

from .client import USER_AGENT, GameyfinClient, GameyfinError, urlopen

CHUNK = 1024 * 1024
SPACE_MARGIN = 512 * 1024 * 1024
TMP_DIRNAME = ".gameyfin-tmp"
MARKER = ".gameyfin.json"

# progress(phase, done, total)
Progress = Callable[[str, int, int | None], None]
CancelCheck = Callable[[], bool]


class Cancelled(Exception):
    pass


@dataclass
class InstallResult:
    install_dir: str
    archive_bytes: int
    installed_bytes: int


# ---- naming ----------------------------------------------------------------

_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def safe_dirname(title: str) -> str:
    name = _ILLEGAL.sub("", title or "").strip().strip(".")
    name = re.sub(r"\s+", " ", name)
    return name[:120] or "game"


def choose_install_dir(dest_root: str, title: str, game_id: str) -> str:
    """<root>/<Title>. If taken by something that isn't this game, add the id."""
    base = os.path.join(dest_root, safe_dirname(title))
    if not os.path.exists(base) or _marker_game_id(base) == str(game_id):
        return base
    return f"{base} [gameyfin-{game_id}]"


def _marker_game_id(path: str) -> str | None:
    try:
        with open(os.path.join(path, MARKER), encoding="utf-8") as f:
            return str(json.load(f).get("game_id"))
    except (OSError, ValueError):
        return None


# ---- disk space ------------------------------------------------------------


def free_bytes(path: str) -> int:
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize


def check_space(dest_root: str, size: int | None) -> None:
    """Archive + extracted copy coexist briefly: need ~2x plus margin."""
    if not size:
        return
    need = size * 2 + SPACE_MARGIN
    have = free_bytes(dest_root)
    if have < need:
        gib = 1024**3
        raise GameyfinError(
            f"Not enough free space: need {need / gib:.1f} GiB, have {have / gib:.1f} GiB", code="no_space"
        )


# ---- download --------------------------------------------------------------


def _filename_from_disposition(value: str | None) -> str | None:
    if not value:
        return None
    msg = email.message.Message()
    msg["content-disposition"] = value
    name = msg.get_filename()  # handles RFC 2231 filename*=UTF-8''...
    return os.path.basename(name) if name else None


def pick_provider(client: GameyfinClient) -> str:
    providers = client.download_providers()  # server sorts by priority desc
    if not providers:
        raise GameyfinError("Server has no download providers enabled", code="no_provider")
    # Prefer a direct (byte-stream) provider; link providers (e.g. torrent) may hand back URLs we can't follow.
    direct = [p for p in providers if "direct" in f"{p.get('id', '')} {p.get('name', '')}".lower()]
    return (direct or providers)[0]["id"]


def _stream_to_file(resp, path: str, total: int | None, progress: Progress, cancelled: CancelCheck) -> int:
    done = 0
    last = 0.0
    with open(path, "wb") as out:
        while True:
            if cancelled():
                raise Cancelled()
            try:
                buf = resp.read(CHUNK)
            except (OSError, http.client.HTTPException) as e:  # timeout, reset, bad chunking
                raise GameyfinError(f"Download interrupted after {done} bytes: {e}", code="network") from None
            if not buf:
                break
            out.write(buf)
            done += len(buf)
            now = time.monotonic()
            if now - last >= 0.25:
                progress("downloading", done, total)
                last = now
    progress("downloading", done, total)
    if total is not None and done != total:
        raise GameyfinError(f"Download incomplete ({done} of {total} bytes); connection dropped", code="truncated")
    return done


def download(
    client: GameyfinClient,
    game_id: str,
    provider: str,
    part_path: str,
    progress: Progress,
    cancelled: CancelCheck,
) -> tuple[int, str | None]:
    """Download to part_path. Returns (bytes, filename from Content-Disposition)."""
    resp = client.open_download(game_id, provider)
    try:
        ctype = resp.headers.get_content_type()
        if ctype == "application/json":
            link = json.loads(resp.read())
            resp.close()
            url = link.get("url") or ""
            if urllib.parse.urlparse(url).scheme not in ("http", "https"):
                raise GameyfinError(f"Unsupported download link ({url.split(':', 1)[0]})", code="unsupported_link")
            # Follow without X-API-Key, per the Gameyfin API contract.
            try:
                resp = urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}),
                                              timeout=60)
            except urllib.error.HTTPError as e:
                raise GameyfinError(f"Download link failed: HTTP {e.code}", status=e.code, code="link_failed") from None
            except (OSError, http.client.HTTPException) as e:
                raise GameyfinError(f"Download link failed: {e}", code="unreachable") from None
        length = resp.headers.get("Content-Length")
        total = int(length) if length and length.isdigit() else None
        name = _filename_from_disposition(resp.headers.get("Content-Disposition"))
        return _stream_to_file(resp, part_path, total, progress, cancelled), name
    finally:
        resp.close()


# ---- extract ---------------------------------------------------------------


def _safe_member_path(name: str) -> str | None:
    """Zip member -> safe relative path, or None to skip. Blocks zip-slip."""
    name = name.replace("\\", "/")
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise GameyfinError(f"Archive contains absolute path: {name}", code="bad_archive")
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise GameyfinError(f"Archive contains unsafe path: {name}", code="bad_archive")
    return "/".join(parts) or None


def _common_root(names: list[str]) -> str | None:
    """If every member lives under one top-level folder, return it (to strip)."""
    tops = {n.split("/", 1)[0] for n in names}
    if len(tops) == 1 and all("/" in n for n in names):
        return tops.pop()
    return None


def extract_zip(archive: str, target: str, progress: Progress, cancelled: CancelCheck) -> int:
    with zipfile.ZipFile(archive) as zf:
        members = []
        for info in zf.infolist():
            rel = _safe_member_path(info.filename)
            if rel is not None:
                members.append((info, rel))
        files = [(i, r) for i, r in members if not i.is_dir()]
        strip = _common_root([r for _, r in files]) if files else None
        total = sum(i.file_size for i, _ in files)
        done = 0
        last = 0.0
        os.makedirs(target, exist_ok=True)
        for info, rel in members:
            if strip:
                rel = rel[len(strip) + 1 :] if rel.startswith(strip + "/") else ""
                if not rel:
                    continue
            dest = os.path.join(target, rel)
            if info.is_dir():
                os.makedirs(dest, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with zf.open(info) as src, open(dest, "wb") as out:
                while True:
                    if cancelled():
                        raise Cancelled()
                    buf = src.read(CHUNK)
                    if not buf:
                        break
                    out.write(buf)
                    done += len(buf)
                    now = time.monotonic()
                    if now - last >= 0.25:
                        progress("extracting", done, total)
                        last = now
            # Preserve unix exec bits if the archive carries them (Linux builds).
            mode = (info.external_attr >> 16) & 0o777
            if mode & 0o111:
                os.chmod(dest, mode | 0o600)
        progress("extracting", done, total)
        return done


# ---- orchestration ---------------------------------------------------------


def _rmtree(path: str) -> None:
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
    elif os.path.exists(path):
        os.remove(path)


def install(
    client: GameyfinClient,
    game: dict,
    dest_root: str,
    job_id: str,
    progress: Progress,
    cancelled: CancelCheck,
    provider: str | None = None,
    install_dir: str | None = None,
) -> InstallResult:
    """Full install. ``game`` is a GameV1 dict (needs id, title, fileSize).

    ``install_dir``: replace this folder (an update) if it is free or ours,
    even if the game was renamed on the server since it was installed.
    """
    game_id = str(game["id"])
    title = game.get("title") or f"game-{game_id}"
    os.makedirs(dest_root, exist_ok=True)
    check_space(dest_root, game.get("fileSize"))

    tmp_dir = os.path.join(dest_root, TMP_DIRNAME)
    os.makedirs(tmp_dir, exist_ok=True)
    part = os.path.join(tmp_dir, f"{job_id}.part")
    staging = os.path.join(tmp_dir, f"{job_id}.staging")

    try:
        progress("downloading", 0, game.get("fileSize"))
        provider = provider or pick_provider(client)
        archive_bytes, filename = download(client, game_id, provider, part, progress, cancelled)

        _rmtree(staging)
        if zipfile.is_zipfile(part):
            installed = extract_zip(part, staging, progress, cancelled)
        else:
            os.makedirs(staging, exist_ok=True)
            # The server's filename could be '..' or empty after sanitising.
            name = safe_dirname(filename) if filename else safe_dirname(title)
            os.replace(part, os.path.join(staging, name))
            installed = archive_bytes
        _rmtree(part)

        progress("finalizing", installed, installed)
        with open(os.path.join(staging, MARKER), "w", encoding="utf-8") as f:
            json.dump({"game_id": game_id, "title": title, "installed_at": int(time.time())}, f)
        # Decide the folder only now: another install of a same-titled game may have
        # finished while we downloaded, and picking earlier would delete its files.
        if not (install_dir and (not os.path.exists(install_dir) or _marker_game_id(install_dir) == game_id)):
            install_dir = choose_install_dir(dest_root, title, game_id)
        if os.path.exists(install_dir):  # reinstall of the same game
            _rmtree(install_dir)
        os.replace(staging, install_dir)  # same filesystem: atomic
        return InstallResult(install_dir, archive_bytes, installed)
    finally:
        _rmtree(part)
        _rmtree(staging)
        try:
            os.rmdir(tmp_dir)  # only if empty (other jobs may be using it)
        except OSError:
            pass
