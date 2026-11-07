"""Pick the game executable inside an installed folder: Windows .exe (run under
Proton) or a native Linux binary/launcher script (run directly)."""

from __future__ import annotations

import fnmatch
import json
import os
import re
import stat

MAX_DEPTH = 4

# Lower-case globs for helpers that are never the game itself.
EXCLUDE = (
    "unitycrashhandler*", "crashpad*", "crashreport*", "*crashhandler*", "*crash_reporter*",
    "vc_redist*", "vcredist*", "dxsetup*", "dxwebsetup*", "directx*", "dotnet*", "ndp*", "oalinst*",
    "physx*", "*uninst*", "unins*", "*setup*", "*install*", "*redist*", "ue4prereq*", "ueprereq*",
    "*launcherhelper*", "easyanticheat*", "start_protected_game*", "*eac*setup*", "notification_helper*",
    "dowser*", "cefsharp*", "*subprocess*", "*webhelper*", "zfgamebrowser*", "quicksfv*", "scriptinterpreter*",
    "patch_*",  # GOG patch installers left next to an unpacked game
    # Linux helpers
    "chrome-sandbox", "chrome_crashpad_handler", "xdg-*", "*.so", "*.so.*", "ldd*", "steam_appid*",
)
SKIP_DIRS = {"_commonredist", "redist", "redistributables", "directx", "vcredist", "__installer",
             "_redist", "__redist", "__support", "support", "prereqs", "prerequisites", "engine"}

# Extensions that mark a Linux launcher; extensionless files count if they are ELF.
LINUX_EXTS = (".x86_64", ".x86", ".sh", ".appimage")
WINDOWS = "windows"
LINUX = "linux"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _excluded(name: str) -> bool:
    n = name.lower()
    return any(fnmatch.fnmatch(n, pat) for pat in EXCLUDE)


def _magic(path: str, n: int = 4) -> bytes:
    try:
        with open(path, "rb") as f:
            return f.read(n)
    except OSError:
        return b""


def is_windows_exe(rel: str) -> bool:
    return rel.lower().endswith((".exe", ".bat", ".msi"))


def kind_of(fn: str, full: str) -> str | None:
    """'windows' | 'linux' | None (not a launch candidate)."""
    low = fn.lower()
    if low.endswith(".exe"):
        return WINDOWS
    if low.endswith(LINUX_EXTS):
        return LINUX
    if "." not in fn and _magic(full) == b"\x7fELF":
        return LINUX
    return None


def find_executables(install_dir: str, title: str = "", prefer: str | None = None) -> list[dict]:
    """Ranked candidates: [{path (relative), size, depth, name_match, kind}], best first.

    ``prefer`` puts that kind first. Without it, Windows wins when both exist,
    because that is what most of a Gameyfin PC library is.
    """
    want = _norm(title)
    found = []
    root_depth = install_dir.rstrip("/").count("/")
    for dirpath, dirnames, filenames in os.walk(install_dir):
        depth = dirpath.rstrip("/").count("/") - root_depth
        dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS and not d.startswith(".")
                       and depth < MAX_DEPTH]
        for fn in filenames:
            if fn.startswith(".") or _excluded(fn):
                continue
            full = os.path.join(dirpath, fn)
            kind = kind_of(fn, full)
            if kind is None:
                continue
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            stem = _norm(os.path.splitext(fn)[0] if "." in fn else fn)
            # Name match: exact > title contains stem / stem contains title.
            name_score = 3 if want and stem == want else 2 if want and stem and (stem in want or want in stem) else 0
            # Shipping builds of UE games live under <Game>/Binaries/Win64.
            ship = 1 if "shipping" in stem or "binaries/win64" in dirpath.lower().replace("\\", "/") else 0
            # GOG's Linux builds launch through start.sh at the root.
            if kind == LINUX and fn == "start.sh" and depth == 0:
                name_score = max(name_score, 3)
            found.append({"path": os.path.relpath(full, install_dir), "size": size, "depth": depth,
                          "name_match": name_score > 0, "kind": kind,
                          "_key": (name_score, ship, -depth, size)})
    kinds = {c["kind"] for c in found}
    first = prefer if prefer in kinds else WINDOWS if WINDOWS in kinds else LINUX
    found.sort(key=lambda c: (c["kind"] == first, c["_key"]), reverse=True)
    for c in found:
        del c["_key"]
    return found


def preferred_kind(platforms: list[str] | None) -> str | None:
    """From Gameyfin platform codes: Linux-only games prefer native binaries."""
    p = set(platforms or [])
    if "LINUX" in p and "PC_MICROSOFT_WINDOWS" not in p:
        return LINUX
    if "PC_MICROSOFT_WINDOWS" in p and "LINUX" not in p:
        return WINDOWS
    return None


def read_gog_infos(install_dir: str) -> list[tuple[str, dict]]:
    """The top-level goggame-<id>.info files as (name, parsed dict); unreadable ones skipped."""
    try:
        names = sorted(n for n in os.listdir(install_dir) if n.startswith("goggame-") and n.endswith(".info"))
    except OSError:
        return []
    out = []
    for name in names:
        try:
            with open(os.path.join(install_dir, name), encoding="utf-8-sig") as f:
                info = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(info, dict):
            out.append((name, info))
    return out


def is_gog_dlc(info: dict) -> bool:
    """DLC info files point rootGameId at the base game; the base game's equals its gameId."""
    gid, root = str(info.get("gameId") or ""), str(info.get("rootGameId") or "")
    return bool(root and gid and root != gid)


def gog_play_task(install_dir: str) -> dict | None:
    """GOG's goggame-<id>.info names the primary launch target, with arguments and
    working dir (DOSBox/ScummVM titles need them). {path, args, work_dir} or None."""
    loaded = read_gog_infos(install_dir)
    # With DLC installed there are several info files: the base game's comes first.
    loaded.sort(key=lambda x: (is_gog_dlc(x[1]), x[0]))
    for _, info in loaded:
        for t in info.get("playTasks") or []:
            if not isinstance(t, dict):
                continue
            if t.get("isPrimary") and t.get("type") == "FileTask" and t.get("path"):
                rel = t["path"].replace("\\", "/").lstrip("/")
                full = os.path.realpath(os.path.join(install_dir, rel))
                if not full.startswith(os.path.realpath(install_dir) + os.sep) or not os.path.isfile(full):
                    continue
                work = (t.get("workingDir") or "").replace("\\", "/").strip("/")
                return {"path": rel, "args": t.get("arguments") or "", "work_dir": work}
    return None


def is_ambiguous(cands: list[dict]) -> bool:
    """Ask the user unless there is exactly one candidate or a clear winner (within the top kind)."""
    if not cands:
        return False
    same = [c for c in cands if c.get("kind", WINDOWS) == cands[0].get("kind", WINDOWS)]
    if len(same) <= 1:
        return False
    a, b = same[0], same[1]
    if a["name_match"] and not b["name_match"]:
        return False
    return not (a["depth"] <= b["depth"] and a["size"] >= 4 * max(b["size"], 1))


def restore_exec_bits(install_dir: str) -> int:
    """Gameyfin's zips (Java ZipOutputStream) carry no Unix modes, so native binaries
    arrive non-executable. Mark ELF files and shebang scripts u+x. Returns the count."""
    n = 0
    for dirpath, _, filenames in os.walk(install_dir):
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            try:
                st = os.lstat(full)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode) or st.st_mode & stat.S_IXUSR:
                continue
            head = _magic(full)
            if head == b"\x7fELF" or head[:2] == b"#!":
                os.chmod(full, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                n += 1
    return n


def ensure_executable(install_dir: str, rel: str) -> None:
    """u+x on one chosen launcher (inside install_dir only)."""
    root = os.path.realpath(install_dir)
    full = os.path.realpath(os.path.join(root, rel))
    if not full.startswith(root + os.sep) or not os.path.isfile(full):
        return
    mode = os.stat(full).st_mode
    if not mode & stat.S_IXUSR:
        os.chmod(full, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
