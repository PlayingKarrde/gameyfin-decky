"""Is there a newer release of this plugin on GitHub? (It isn't on the Decky store, so
Decky's own update check never sees it.)"""

from __future__ import annotations

import json
import re
import time
import urllib.request

from .client import USER_AGENT, urlopen

REPO = "PlayingKarrde/gameyfin-decky"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
CACHE_SECONDS = 6 * 3600

_cache: dict = {"at": 0.0, "data": None}


def parse_version(v: str) -> tuple[int, ...] | None:
    m = re.match(r"^v?(\d+(?:\.\d+)*)$", (v or "").strip())
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def is_newer(latest: str, current: str) -> bool:
    a, b = parse_version(latest), parse_version(current)
    if a is None or b is None:
        return False
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def latest_release(fetch=None) -> dict:
    """{version, url (the zip), sha256 or None, page}. Raises on network/HTTP errors."""
    if fetch is None:
        req = urllib.request.Request(LATEST_URL, headers={"User-Agent": USER_AGENT,
                                                          "Accept": "application/vnd.github+json"})
        with urlopen(req, timeout=15) as resp:
            data = json.load(resp)
    else:
        data = fetch()
    tag = data.get("tag_name") or ""
    zips = [a for a in data.get("assets") or []
            if str(a.get("name", "")).startswith("gameyfin-decky-") and str(a.get("name", "")).endswith(".zip")]
    asset = zips[0] if zips else None
    digest = (asset or {}).get("digest") or ""
    return {
        "version": tag.lstrip("v"),
        "url": asset.get("browser_download_url") if asset else None,
        "sha256": digest.split(":", 1)[1] if digest.startswith("sha256:") else None,
        "page": data.get("html_url"),
    }


def check(current: str, force: bool = False, fetch=None) -> dict:
    """{current, latest, newer, url, sha256, page}; cached for a few hours."""
    now = time.time()
    if force or _cache["data"] is None or now - _cache["at"] > CACHE_SECONDS:
        _cache["data"], _cache["at"] = latest_release(fetch), now
    rel = _cache["data"]
    return {"current": current, "latest": rel["version"], "newer": bool(rel["url"]) and is_newer(rel["version"], current),
            "url": rel["url"], "sha256": rel["sha256"], "page": rel["page"]}
