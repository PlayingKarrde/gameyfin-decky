"""Pick the game executable inside an installed folder."""

from __future__ import annotations

import fnmatch
import os
import re

MAX_DEPTH = 4

# Lower-case globs for helpers that are never the game itself.
EXCLUDE = (
    "unitycrashhandler*", "crashpad*", "crashreport*", "*crashhandler*", "*crash_reporter*",
    "vc_redist*", "vcredist*", "dxsetup*", "dxwebsetup*", "directx*", "dotnet*", "ndp*", "oalinst*",
    "physx*", "*uninst*", "unins*", "*setup*", "*install*", "*redist*", "ue4prereq*", "ueprereq*",
    "*launcherhelper*", "easyanticheat*", "start_protected_game*", "*eac*setup*", "notification_helper*",
    "dowser*", "cefsharp*", "*subprocess*", "*webhelper*", "zfgamebrowser*", "quicksfv*",
)
SKIP_DIRS = {"_commonredist", "redist", "redistributables", "directx", "vcredist", "__installer",
             "_redist", "support", "prereqs", "prerequisites", "engine"}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _excluded(name: str) -> bool:
    n = name.lower()
    return any(fnmatch.fnmatch(n, pat) for pat in EXCLUDE)


def find_executables(install_dir: str, title: str = "") -> list[dict]:
    """Ranked candidates: [{path (relative), size, depth}], best first."""
    want = _norm(title)
    found = []
    root_depth = install_dir.rstrip("/").count("/")
    for dirpath, dirnames, filenames in os.walk(install_dir):
        depth = dirpath.rstrip("/").count("/") - root_depth
        dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS and not d.startswith(".")
                       and depth < MAX_DEPTH]
        for fn in filenames:
            if not fn.lower().endswith(".exe") or _excluded(fn):
                continue
            full = os.path.join(dirpath, fn)
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            stem = _norm(fn[:-4])
            # Name match: exact > title contains stem / stem contains title.
            name_score = 3 if want and stem == want else 2 if want and stem and (stem in want or want in stem) else 0
            # Shipping builds of UE games live under <Game>/Binaries/Win64.
            ship = 1 if "shipping" in stem or "binaries/win64" in dirpath.lower().replace("\\", "/") else 0
            found.append({"path": os.path.relpath(full, install_dir), "size": size, "depth": depth,
                          "name_match": name_score > 0, "_key": (name_score, ship, -depth, size)})
    found.sort(key=lambda c: c["_key"], reverse=True)
    for c in found:
        del c["_key"]
    return found


def is_ambiguous(cands: list[dict]) -> bool:
    """Ask the user unless there is exactly one candidate or a clear winner."""
    if len(cands) <= 1:
        return False
    a, b = cands[0], cands[1]
    if a["name_match"] and not b["name_match"]:
        return False
    return not (a["depth"] <= b["depth"] and a["size"] >= 4 * max(b["size"], 1))
