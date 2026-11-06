"""Plugin settings persisted as JSON. The token never leaves the backend."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass


@dataclass
class Settings:
    server_url: str = ""
    token: str = ""
    custom_install_dir: str = ""

    def public(self) -> dict:
        """Safe view for the frontend: no token, just whether one is set."""
        return {"server_url": self.server_url, "has_token": bool(self.token),
                "custom_install_dir": self.custom_install_dir}


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
        # 0600: contains the API token.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(asdict(settings), f, indent=2)
        os.replace(tmp, self.path)
