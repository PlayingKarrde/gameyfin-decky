"""SteamGridDB artwork lookup (stdlib only, like client.py).

The API key is the user's own (steamgriddb.com/profile/preferences/api). It stays
in settings.json and is only ever sent to www.steamgriddb.com.

Matching avoids guessing: Gameyfin's own SteamGridDB metadata plugin usually stores
the SGDB game id in ``externalIds``; failing that a Steam appid maps exactly; a
title search is accepted only on an exact (normalized) name match. No match means
no SGDB art, never the wrong game's art.
"""

from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .client import USER_AGENT, GameyfinError, Image, urlopen

API = "https://www.steamgriddb.com/api/v2"
KEY_PAGE = "https://www.steamgriddb.com/profile/preferences/api"
TIMEOUT = 15.0
MAX_IMAGE_BYTES = 25 * 1024 * 1024

_PROVIDER_SGDB = "steamgriddb"
_PROVIDER_STEAM = "steam"
_STATIC_IMAGES = "image/png,image/jpeg,image/webp"
_FILTERS = {"types": "static", "nsfw": "false", "humor": "false", "epilepsy": "false"}
_PORTRAIT = ("600x900", "342x482", "660x930")
_WIDE = ("920x430", "460x215")
_SQUARE = ("1024x1024", "512x512")


def is_sgdb_image_url(url: str) -> bool:
    """Only SGDB's own HTTPS hosts (the CDN) may be fetched through the plugin."""
    try:
        p = urllib.parse.urlparse(url or "")
    except ValueError:
        return False
    host = (p.hostname or "").lower()
    return p.scheme == "https" and (host == "steamgriddb.com" or host.endswith(".steamgriddb.com"))


def normalize_title(s: str) -> str:
    s = (s or "").lower().replace("&", "and")
    s = re.sub(r"[™®©]", "", s)
    return re.sub(r"[^a-z0-9]+", "", s)


def external_id(game: dict, provider: str) -> str | None:
    """externalIds is [{provider: 'org.gameyfin.plugins.metadata.<name>', id}]."""
    for x in game.get("externalIds") or []:
        if isinstance(x, dict) and str(x.get("provider", "")).rsplit(".", 1)[-1] == provider and x.get("id"):
            return str(x["id"])
    return None


def _best(items: list[dict], dimensions: tuple[str, ...] | None = None) -> str | None:
    """Highest-scored URL, optionally limited to the given WxH sizes (in preference order)."""
    if dimensions:
        for dim in dimensions:
            w, h = (int(v) for v in dim.split("x"))
            hit = _best([i for i in items if i.get("width") == w and i.get("height") == h])
            if hit:
                return hit
        return None
    items = [i for i in items if i.get("url")]
    # Python's sort is stable: equal scores keep SGDB's own order.
    items.sort(key=lambda i: -(i.get("score") or 0))
    return items[0]["url"] if items else None


class SgdbClient:
    def __init__(self, key: str, timeout: float = TIMEOUT, base: str = API):
        self.key = (key or "").strip()
        self.timeout = timeout
        self.base = base.rstrip("/")

    def _get(self, path: str, params: dict[str, str] | None = None) -> Any:
        url = self.base + path + ("?" + urllib.parse.urlencode(params) if params else "")
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT, "Accept": "application/json", "Authorization": f"Bearer {self.key}"})
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise GameyfinError("SteamGridDB rejected the API key", status=401, code="sgdb_key") from None
            if e.code == 404:
                return None
            raise GameyfinError(f"SteamGridDB error {e.code}", status=e.code, code="sgdb_error") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise GameyfinError(f"Can't reach SteamGridDB: {getattr(e, 'reason', e)}", code="sgdb_unreachable") from None
        except ValueError:
            raise GameyfinError("Unexpected response from SteamGridDB", code="sgdb_error") from None
        if not isinstance(body, dict) or not body.get("success"):
            return None
        return body.get("data")

    def validate(self) -> None:
        """Raises GameyfinError(code='sgdb_key') if the key is wrong."""
        if not self.key:
            raise GameyfinError("SteamGridDB API key is empty", code="sgdb_key")
        self._get("/search/autocomplete/" + urllib.parse.quote("portal"))

    def resolve(self, game: dict) -> int | None:
        """SGDB game id for a Gameyfin GameV1, or None."""
        sid = external_id(game, _PROVIDER_SGDB)
        if sid and sid.isdigit():
            return int(sid)
        appid = external_id(game, _PROVIDER_STEAM)
        if appid and appid.isdigit():
            data = self._get(f"/games/steam/{appid}")
            if isinstance(data, dict) and data.get("id"):
                return int(data["id"])
        want = normalize_title(game.get("title") or "")
        if not want:
            return None
        results = [r for r in self._get("/search/autocomplete/" + urllib.parse.quote(game["title"], safe="")) or []
                   if isinstance(r, dict) and r.get("id")]
        for r in results:
            if normalize_title(r.get("name") or "") == want:
                return int(r["id"])
        # "AM2R: Return of Samus" is listed as "AM2R". Accept the base title only when it is
        # the sole result, so "Batman: Arkham Asylum" can't land on some other "Batman".
        base = normalize_title(re.split(r":| - | – ", game["title"], maxsplit=1)[0])
        if len(results) == 1 and base and base != want and normalize_title(results[0].get("name") or "") == base:
            return int(results[0]["id"])
        return None

    def assets(self, sgdb_id: int) -> dict:
        """{grid, square, wide, hero, logo}: the top-voted static URL of each, or None."""
        def get(kind: str, extra: dict[str, str]) -> list[dict]:
            data = self._get(f"/{kind}/game/{sgdb_id}", {**_FILTERS, **extra})
            return [d for d in data or [] if isinstance(d, dict)]

        grids = get("grids", {"dimensions": ",".join(_PORTRAIT + _WIDE + _SQUARE), "mimes": _STATIC_IMAGES})
        return {
            "grid": _best(grids, _PORTRAIT),
            "square": _best(grids, _SQUARE),
            "wide": _best(grids, _WIDE),
            "hero": _best(get("heroes", {"mimes": _STATIC_IMAGES})),
            "logo": _best(get("logos", {"mimes": "image/png,image/webp"})),
        }


class SgdbResolver:
    """Remembers resolved ids for the session so reinstalls and refreshes skip the search."""

    def __init__(self):
        self._ids: dict[str, int | None] = {}
        self._lock = threading.Lock()

    def assets_for(self, client: SgdbClient, game: dict) -> dict:
        gid = str(game.get("id"))
        with self._lock:
            known = gid in self._ids
            sgdb_id = self._ids.get(gid)
        if not known:
            sgdb_id = client.resolve(game)
            with self._lock:
                self._ids[gid] = sgdb_id
        return client.assets(sgdb_id) if sgdb_id else {}


def fetch_image(url: str, timeout: float = 30.0) -> Image:
    """Download a public SGDB CDN image (no API key is sent)."""
    if not is_sgdb_image_url(url):
        raise GameyfinError(f"Refusing to fetch non-SteamGridDB URL: {url}", code="bad_image")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "image/*"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = resp.read(MAX_IMAGE_BYTES + 1)
            ctype = resp.headers.get_content_type() or "application/octet-stream"
    except urllib.error.HTTPError as e:
        raise GameyfinError(f"SteamGridDB image error {e.code}", status=e.code, code="sgdb_error") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise GameyfinError(f"Can't reach SteamGridDB: {getattr(e, 'reason', e)}", code="sgdb_unreachable") from None
    if len(data) > MAX_IMAGE_BYTES:
        raise GameyfinError("SteamGridDB image is too large", code="bad_image")
    return Image(data, ctype)


def art_plan(gameyfin: dict, sgdb: dict, square: bool = False) -> dict:
    """Pick one URL per Steam slot. Gameyfin's cover wins the portrait capsule (it's what the
    user curated); SGDB fills the slots Gameyfin has nothing sized for. With ``square`` the
    capsule is SGDB's square grid instead, falling back to the usual poster."""
    images = [i.get("url") for i in gameyfin.get("images") or [] if isinstance(i, dict) and i.get("url")]
    gf_cover = (gameyfin.get("cover") or {}).get("url") if isinstance(gameyfin.get("cover"), dict) else None
    gf_header = (gameyfin.get("header") or {}).get("url") if isinstance(gameyfin.get("header"), dict) else None
    return {
        "capsule": (square and sgdb.get("square")) or gf_cover or sgdb.get("grid"),
        "wide": sgdb.get("wide") or gf_header,
        "hero": sgdb.get("hero") or gf_header or (images[0] if images else None),
        "logo": sgdb.get("logo"),
    }
