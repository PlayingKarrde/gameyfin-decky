"""Local record of installed games, and where games can be installed."""

from __future__ import annotations

import json
import os
import shutil
import time

from .client import GameyfinError
from .installer import MARKER, free_bytes


class InstalledStore:
    """{game_id: {title, install_dir, exe, appid, installed_at, size}} in installed.json."""

    def __init__(self, directory: str):
        self.path = os.path.join(directory, "installed.json")

    def load(self) -> dict[str, dict]:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, data: dict) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self.path)

    def get(self, game_id: str) -> dict | None:
        return self.load().get(str(game_id))

    def put(self, game_id: str, record: dict) -> dict:
        data = self.load()
        rec = {**data.get(str(game_id), {}), **record, "game_id": str(game_id)}
        rec["installed_at"] = int(time.time())
        data[str(game_id)] = rec
        self._save(data)
        return rec

    def remove(self, game_id: str) -> dict | None:
        data = self.load()
        rec = data.pop(str(game_id), None)
        self._save(data)
        return rec


def delete_game_dir(install_dir: str, game_id: str) -> None:
    """Delete an install folder, but only if our marker says it's this game."""
    if not os.path.isdir(install_dir):
        return
    try:
        with open(os.path.join(install_dir, MARKER), encoding="utf-8") as f:
            marker = json.load(f)
    except (OSError, ValueError):
        raise GameyfinError(f"Refusing to delete {install_dir}: no Gameyfin marker", code="unsafe_delete")
    if str(marker.get("game_id")) != str(game_id):
        raise GameyfinError(f"Refusing to delete {install_dir}: belongs to another game", code="unsafe_delete")
    shutil.rmtree(install_dir)


def delete_prefix(steam_root: str, appid: int) -> bool:
    path = os.path.join(steam_root, "steamapps", "compatdata", str(int(appid)))
    if os.path.isdir(path):
        shutil.rmtree(path)
        return True
    return False


# ---- install targets ---------------------------------------------------------


def _removable_mounts() -> list[str]:
    out = []
    try:
        with open("/proc/mounts", encoding="utf-8") as f:
            for line in f:
                mnt = line.split()[1].encode().decode("unicode_escape")
                if mnt.startswith("/run/media/"):
                    out.append(mnt)
    except OSError:
        pass
    return out


def install_targets(home: str, custom: str = "") -> list[dict]:
    """[{id, label, path, free}] — path is the games root (created on install)."""
    targets = [{"id": "internal", "label": "Internal storage", "path": os.path.join(home, "Games", "Gameyfin"),
                "probe": home}]
    for mnt in _removable_mounts():
        targets.append({"id": f"sd:{mnt}", "label": f"SD card ({os.path.basename(mnt)})",
                        "path": os.path.join(mnt, "Games", "Gameyfin"), "probe": mnt})
    if custom:
        targets.append({"id": "custom", "label": "Custom folder", "path": custom,
                        "probe": _existing_parent(custom)})
    for t in targets:
        try:
            t["free"] = free_bytes(t.pop("probe"))
        except OSError:
            t["free"] = None
    return targets


def _existing_parent(path: str) -> str:
    while path and not os.path.exists(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return path or "/"
