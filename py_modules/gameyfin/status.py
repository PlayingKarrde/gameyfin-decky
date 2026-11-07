"""Health and update status of installed games.

Files are checked locally. Updates compare the server's current ``fileSize``
with the size recorded at install time. ``updatedAt`` is not used: Gameyfin
bumps it on every metadata refresh, so it would flag games that never changed.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from .client import GameyfinError
from .installer import _marker_game_id
from .library import game_summary


def files_state(install_dir: str | None, game_id: str) -> str:
    """'ok' | 'missing' (folder gone) | 'unmarked' (folder exists but isn't ours)."""
    if not install_dir or not os.path.isdir(install_dir):
        return "missing"
    return "ok" if _marker_game_id(install_dir) == str(game_id) else "unmarked"


def recorded_server_size(rec: dict) -> int | None:
    # Records made before 0.2.0 lack server_file_size; their installed size equals the
    # server's fileSize for folder games (STORED zip of the same files).
    return rec.get("server_file_size") or rec.get("size")


def _fallback_summary(rec: dict) -> dict:
    return {"id": str(rec["game_id"]), "title": rec.get("title") or f"Game {rec['game_id']}", "platforms": [],
            "release": None, "file_size": rec.get("size"), "cover": None}


def check_one(get_game: Callable[[str], dict] | None, rec: dict) -> dict:
    gid = str(rec["game_id"])
    out = {"game_id": gid, "files": files_state(rec.get("install_dir"), gid), "update_available": False,
           "server_missing": False, "server_size": None, "summary": _fallback_summary(rec), "error": None}
    if get_game is None:
        return out
    try:
        game = get_game(gid)
    except GameyfinError as e:
        if e.status == 404:
            out["server_missing"] = True
        else:
            out["error"] = str(e)
        return out
    out["summary"] = game_summary(game)
    size = game.get("fileSize")
    out["server_size"] = size
    have = recorded_server_size(rec)
    out["update_available"] = bool(size and have and size != have and out["files"] != "missing")
    return out


def check_all(get_game: Callable[[str], dict] | None, records: list[dict]) -> list[dict]:
    if not records:
        return []
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(lambda r: check_one(get_game, r), records))
