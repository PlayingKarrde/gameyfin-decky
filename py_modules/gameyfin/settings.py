"""Plugin settings persisted as JSON. The token and SteamGridDB key never leave the backend."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass


@dataclass
class Settings:
    server_url: str = ""
    token: str = ""
    custom_install_dir: str = ""
    # Run bundled VC++/DirectX/... installers in the prefix on a game's first launch.
    install_deps: bool = True
    # The user's own SteamGridDB API key (optional): adds logos, heroes and wide capsules.
    sgdb_key: str = ""
    # Use SteamGridDB's square grids for the library capsule instead of the poster.
    sgdb_square_covers: bool = False

    def public(self) -> dict:
        """Safe view for the frontend: no token, just whether one is set."""
        return {"server_url": self.server_url, "has_token": bool(self.token),
                "custom_install_dir": self.custom_install_dir, "install_deps": self.install_deps,
                "has_sgdb_key": bool(self.sgdb_key), "sgdb_square_covers": self.sgdb_square_covers}


class SettingsStore:
    def __init__(self, directory: str):
        self.path = os.path.join(directory, "settings.json")

    def load(self) -> Settings:
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
        except FileNotFoundError:
            return Settings()
        except (OSError, ValueError):
            # Unreadable/corrupt: start unconfigured rather than fail plugin load.
            return Settings()
        if not isinstance(raw, dict):
            return Settings()
        known = {k: v for k, v in raw.items() if k in Settings.__dataclass_fields__}
        return Settings(**known)

    def save(self, settings: Settings) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        # 0600: contains the API token and SteamGridDB key.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(asdict(settings), f, indent=2)
        os.replace(tmp, self.path)
