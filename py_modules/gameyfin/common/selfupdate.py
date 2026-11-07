"""Is there a newer release of this plugin on GitHub? (The plugins aren't on the Decky
store, so Decky's own update check never sees them.)

    UPDATER = Updater("PlayingKarrde/romm-decky", "romm-decky-")
    UPDATER.check(decky.DECKY_PLUGIN_VERSION)
"""

from __future__ import annotations

import json
import re
import time
import urllib.request

from . import net

CACHE_SECONDS = 6 * 3600


def parse_version(v: str) -> tuple[int, ...] | None:
    m = re.match(r"^v?(\d+(?:\.\d+)*)$", (v or "").strip())
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def is_newer(latest: str, current: str) -> bool:
    a, b = parse_version(latest), parse_version(current)
    if a is None or b is None:
        return False
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


class Updater:
    def __init__(self, repo: str, asset_prefix: str):
        """``repo``: owner/name on GitHub. ``asset_prefix``: the release zip's name before the version."""
        self.latest_url = f"https://api.github.com/repos/{repo}/releases/latest"
        self.asset_prefix = asset_prefix
        self._at = 0.0
        self._data: dict | None = None

    def latest_release(self, fetch=None) -> dict:
        """{version, url (the zip), sha256 or None, page}. Raises on network/HTTP errors."""
        if fetch is None:
            req = urllib.request.Request(self.latest_url, headers={"User-Agent": net.user_agent(),
                                                                   "Accept": "application/vnd.github+json"})
            with net.urlopen(req, timeout=15) as resp:
                data = json.load(resp)
        else:
            data = fetch()
        tag = data.get("tag_name") or ""
        zips = [a for a in data.get("assets") or []
                if str(a.get("name", "")).startswith(self.asset_prefix) and str(a.get("name", "")).endswith(".zip")]
        asset = zips[0] if zips else None
        digest = (asset or {}).get("digest") or ""
        return {
            "version": tag.lstrip("v"),
            "url": asset.get("browser_download_url") if asset else None,
            "sha256": digest.split(":", 1)[1] if digest.startswith("sha256:") else None,
            "page": data.get("html_url"),
        }

    def check(self, current: str, force: bool = False, fetch=None) -> dict:
        """{current, latest, newer, url, sha256, page}; cached for a few hours."""
        now = time.time()
        if force or self._data is None or now - self._at > CACHE_SECONDS:
            self._data, self._at = self.latest_release(fetch), now
        rel = self._data
        return {"current": current, "latest": rel["version"],
                "newer": bool(rel["url"]) and is_newer(rel["version"], current),
                "url": rel["url"], "sha256": rel["sha256"], "page": rel["page"]}
