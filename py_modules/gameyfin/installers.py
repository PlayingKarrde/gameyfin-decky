"""Turn a downloaded installer (GOG-style Inno Setup ``setup_*.exe`` + ``.bin`` parts)
into an installed game folder, using a bundled ``innoextract``. No Wine needed.

Layout after a Gameyfin download of a GOG offline installer:

    <install_dir>/setup_game_1.0_(12345).exe
    <install_dir>/setup_game_1.0_(12345)-1.bin
    <install_dir>/setup_game_1.0_(12345)-2.bin
    <install_dir>/setup_game_some_dlc_1.0_(12346).exe     # optional: each DLC has its own installer
    <install_dir>/patch_game_0.9_to_1.0.exe               # optional: left alone (binary diffs)

DLC installs into the same folder as the base game (that is what GOG's installers and
Galaxy do), so each installer is extracted separately, then the base game is moved in
and every DLC is layered on top (DLC files may replace base files). The base game is
the one whose goggame-<id>.info has gameId == rootGameId; DLC info files point their
rootGameId at the base game.

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

from .exes import is_gog_dlc, read_gog_infos
from .installer import MARKER, Cancelled

# GOG offline installers are "setup_<name>_<version>_(<build>).exe"; also accept
# plain setup.exe. Part files share the stem: "<stem>-1.bin", "<stem>-2.bin", ...
_SETUP_RE = re.compile(r"^setup(_.+)?\.exe$", re.IGNORECASE)
# GOG patch installers (old version -> new version diffs). innoextract can't apply them.
_PATCH_RE = re.compile(r"^patch_.+\.exe$", re.IGNORECASE)

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


def find_installers(install_dir: str) -> list[str]:
    """The installers in this folder if it *is* an installer download: one or more
    ``setup*.exe`` (base game + DLC) and no other runnable .exe besides GOG patches.

    Only the top level counts: an installer next to an already-installed game (a
    bundled redistributable, say) must not hijack the install.
    """
    try:
        names = os.listdir(install_dir)
    except OSError:
        return []
    setups = [n for n in names if _SETUP_RE.match(n) and os.path.isfile(os.path.join(install_dir, n))]
    if not setups:
        return []
    other_exes = [n for n in names if n.lower().endswith(".exe") and n not in setups and not _PATCH_RE.match(n)]
    if other_exes:
        return []
    return [os.path.join(install_dir, n) for n in sorted(setups)]


def find_patches(install_dir: str) -> list[str]:
    try:
        return sorted(n for n in os.listdir(install_dir) if _PATCH_RE.match(n))
    except OSError:
        return []


def installer_parts(setup: str) -> list[str]:
    """The setup file plus its numbered .bin parts ("<stem>-1.bin", ...). Exact stem match:
    a DLC's "setup_game_dlc-1.bin" must not count as a part of "setup_game.exe"."""
    d, base = os.path.split(setup)
    part_re = re.compile(re.escape(os.path.splitext(base)[0]) + r"-\d+\.bin$", re.IGNORECASE)
    return [setup] + [os.path.join(d, n) for n in sorted(os.listdir(d)) if part_re.match(n)]


def _parts_bytes(setup: str) -> int:
    return sum(os.path.getsize(p) for p in installer_parts(setup))


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


def _gog_info(d: str) -> tuple[bool, bool]:
    """(looks like a base game, has a primary play task) from the top-level goggame-*.info files."""
    infos = [info for _, info in read_gog_infos(d)]
    base = any(info.get("gameId") and not is_gog_dlc(info) for info in infos)
    primary = any(isinstance(t, dict) and t.get("isPrimary") for info in infos for t in info.get("playTasks") or [])
    return base, primary


def _top_names(staging: str) -> list[str]:
    return [n for n in os.listdir(staging) if n not in _DROP and n != MARKER]


def _merge(src: str, dst: str, names: list[str] | None = None) -> None:
    """Move src's contents (or just ``names``) into dst; directories merge, files and
    type clashes are replaced."""
    for name in os.listdir(src) if names is None else names:
        s, d = os.path.join(src, name), os.path.join(dst, name)
        if os.path.isdir(s) and not os.path.islink(s) and os.path.isdir(d) and not os.path.islink(d):
            _merge(s, d)
            continue
        if os.path.isdir(d) and not os.path.islink(d):
            shutil.rmtree(d)
        elif os.path.lexists(d):
            os.remove(d)
        os.replace(s, d)


class InstallerResult:
    def __init__(self, installed_bytes: int, dlc: int, warnings: list[str]):
        self.installed_bytes, self.dlc, self.warnings = installed_bytes, dlc, warnings


def install_from_installers(innoextract: str, install_dir: str, setups: list[str], progress: Progress,
                            cancelled: Callable[[], bool]) -> InstallerResult:
    """Replace install_dir's installers with the installed game (base game, then each DLC).

    A failing DLC installer is skipped with a warning and left in the folder; a failing
    base game installer fails the whole install, leaving every installer in place.
    """
    sizes = {s: _parts_bytes(s) for s in setups}
    expected = sum(sizes.values())
    staging_root = os.path.join(install_dir, ".gameyfin-installer")
    shutil.rmtree(staging_root, ignore_errors=True)
    warnings: list[str] = []
    try:
        progress("installing", 0, expected)
        extracted: list[tuple[str, str]] = []
        failed: dict[str, InstallerError] = {}
        done = 0
        # Biggest first: usually the base game, and a failure there stops before the DLC work.
        for i, setup in enumerate(sorted(setups, key=lambda s: -sizes[s])):
            out = os.path.join(staging_root, str(i))
            base_done = done

            def prog(_phase: str, n: int, _total: int | None, base_done: int = base_done) -> None:
                progress("installing", base_done + min(n, sizes[setup]), expected)
            try:
                run_innoextract(innoextract, setup, out, prog, cancelled)
                extracted.append((setup, out))
            except InstallerError as e:
                if len(setups) == 1:
                    raise
                failed[setup] = e
                shutil.rmtree(out, ignore_errors=True)
            done += sizes[setup]
        if not extracted:
            raise next(iter(failed.values()))

        # The base game: GOG metadata says so; failing that, a launchable game, then the biggest.
        scored = [((*_gog_info(out), sizes[setup]), setup, out) for setup, out in extracted]
        scored.sort(key=lambda x: x[0], reverse=True)
        (is_base, _, _), base_setup, base_out = scored[0]
        if not is_base and failed and max(sizes[s] for s in failed) > sizes[base_setup]:
            # The likeliest base game is the one that failed: don't install only its DLC.
            raise failed[max(failed, key=lambda s: sizes[s])]
        order = [(base_setup, base_out)] + [(s, o) for _, s, o in scored[1:]]

        installer_files = {os.path.basename(p) for s in setups for p in installer_parts(s)}
        keep = installer_files | {MARKER, os.path.basename(staging_root)} | set(find_patches(install_dir))
        for _, out in order:  # checked before deleting anything, so a failure leaves the installers intact
            clash = [n for n in _top_names(out) if n not in keep and os.path.exists(os.path.join(install_dir, n))]
            if clash:
                raise InstallerError(f"Unexpected file in the install folder: {clash[0]}")

        # Out with the installers that worked, in with the game. The marker stays where it is.
        for setup, _ in order:
            for p in installer_parts(setup):
                os.remove(p)
        for _, out in order:
            _merge(out, install_dir, _top_names(out))

        for setup, e in failed.items():
            warnings.append(f"DLC installer {os.path.basename(setup)} failed ({e}); it was left in the game folder")
        for name in find_patches(install_dir):
            warnings.append(f"Patch installers aren't supported; {name} was left in the game folder")
        return InstallerResult(_dir_bytes(install_dir), len(order) - 1, warnings)
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)
