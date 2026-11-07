"""Turn a downloaded installer (GOG-style Inno Setup ``setup_*.exe`` + ``.bin`` parts)
into an installed game folder, using a bundled ``innoextract``. No Wine needed.

Layout after a Gameyfin download of a GOG offline installer:

    <install_dir>/setup_game_1.0_(12345).exe
    <install_dir>/setup_game_1.0_(12345)-1.bin
    <install_dir>/setup_game_1.0_(12345)-2.bin

innoextract (1.9) writes the ``{app}`` files at the top of its output dir, plus
``commonappdata/`` (GOG's uninstaller) which we drop; ``--exclude-temp`` skips the
installer's own ``tmp/`` files. We extract into a staging folder inside install_dir
(same filesystem), delete the installer files (they are on the server anyway) and
move the game files up, so the folder looks like any portable install.
Verified on the Deck with GOG's Inno Setup 5.6.2 installer for Lollipop Chainsaw RePOP.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import time
from typing import Callable

from .installer import MARKER, Cancelled

# GOG offline installers are "setup_<name>_<version>_(<build>).exe"; also accept
# plain setup.exe. Part files share the stem: "<stem>-1.bin", "<stem>-2.bin", ...
_SETUP_RE = re.compile(r"^setup(_.+)?\.exe$", re.IGNORECASE)

Progress = Callable[[str, int, int | None], None]

# Top-level entries innoextract may produce that are not part of the game.
_DROP = {"commonappdata", "tmp", "innoextract.log"}
_LOADER = "/lib64/ld-linux-x86-64.so.2"


def innoextract_cmd(innoextract: str) -> list[str]:
    """How to run the bundled binary. Decky's zip install may drop its exec bit and the
    plugin dir is root-owned, so fall back to starting it through the dynamic loader."""
    if os.access(innoextract, os.X_OK):
        return [innoextract]
    if os.path.exists(_LOADER):
        return [_LOADER, innoextract]
    raise InstallerError("Bundled innoextract is not executable")


def find_installer(install_dir: str) -> str | None:
    """Path of the installer if this folder *is* an installer (and nothing else runnable).

    Only the top level counts: an installer next to an already-installed game (a
    bundled redistributable, say) must not hijack the install.
    """
    try:
        names = os.listdir(install_dir)
    except OSError:
        return None
    setups = [n for n in names if _SETUP_RE.match(n) and os.path.isfile(os.path.join(install_dir, n))]
    if len(setups) != 1:
        return None
    other_exes = [n for n in names if n.lower().endswith(".exe") and n not in setups]
    if other_exes:
        return None
    return os.path.join(install_dir, setups[0])


def installer_parts(setup: str) -> list[str]:
    """The setup file plus its .bin parts (same stem)."""
    d, base = os.path.split(setup)
    stem = os.path.splitext(base)[0]
    parts = [setup]
    for n in sorted(os.listdir(d)):
        if n.lower().startswith(stem.lower()) and n.lower().endswith(".bin"):
            parts.append(os.path.join(d, n))
    return parts


def _dir_bytes(path: str) -> int:
    total = 0
    for dp, _, fns in os.walk(path):
        for fn in fns:
            try:
                total += os.lstat(os.path.join(dp, fn)).st_size
            except OSError:
                pass
    return total


class InstallerError(Exception):
    pass


def run_innoextract(innoextract: str, setup: str, out_dir: str, progress: Progress,
                    cancelled: Callable[[], bool], expected: int | None = None) -> None:
    """Extract the installer's {app} files into out_dir/app. Raises InstallerError/Cancelled."""
    os.makedirs(out_dir, exist_ok=True)
    log_path = os.path.join(out_dir, "innoextract.log")
    cmd = [*innoextract_cmd(innoextract), "--extract", "--silent", "--no-extract-unknown", "--exclude-temp",
           "--timestamps", "none", "--output-dir", out_dir, setup]
    with open(log_path, "wb") as log:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                start_new_session=True)
        try:
            last = 0.0
            while proc.poll() is None:
                if cancelled():
                    os.killpg(proc.pid, signal.SIGTERM)
                    proc.wait(timeout=30)
                    raise Cancelled()
                now = time.monotonic()
                if now - last >= 2:
                    progress("installing", _dir_bytes(out_dir), expected)
                    last = now
                time.sleep(0.5)
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
    if proc.returncode != 0:
        with open(log_path, "rb") as f:
            tail = f.read()[-600:].decode("utf-8", "replace").strip().splitlines()
        reason = tail[-1] if tail else f"exit code {proc.returncode}"
        raise InstallerError(f"innoextract failed: {reason}")
    if not [n for n in os.listdir(out_dir) if n not in _DROP]:
        raise InstallerError("innoextract found no game files in the installer")


def install_from_installer(innoextract: str, install_dir: str, setup: str, progress: Progress,
                           cancelled: Callable[[], bool]) -> int:
    """Replace install_dir's contents (the installer) with the installed game. Returns bytes."""
    parts = installer_parts(setup)
    expected = sum(os.path.getsize(p) for p in parts)
    staging = os.path.join(install_dir, ".gameyfin-installer")
    shutil.rmtree(staging, ignore_errors=True)
    try:
        progress("installing", 0, expected)
        run_innoextract(innoextract, setup, staging, progress, cancelled, expected)
        names = [n for n in os.listdir(staging) if n not in _DROP and n != MARKER]
        keep = {os.path.basename(p) for p in parts} | {MARKER, os.path.basename(staging)}
        clash = [n for n in names if n not in keep and os.path.exists(os.path.join(install_dir, n))]
        if clash:  # checked before deleting anything, so a failure leaves the installer intact
            raise InstallerError(f"Unexpected file in the install folder: {clash[0]}")
        # Out with the installer, in with the game. The marker stays where it is.
        for p in parts:
            os.remove(p)
        for name in names:
            os.replace(os.path.join(staging, name), os.path.join(install_dir, name))
        return _dir_bytes(install_dir)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
