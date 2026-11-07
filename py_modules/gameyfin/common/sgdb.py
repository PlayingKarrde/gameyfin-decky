"""SteamGridDB artwork lookup (stdlib only).

The API key is the user's own (steamgriddb.com/profile/preferences/api). It stays in
the plugin's settings.json and is only ever sent to www.steamgriddb.com.

Matching avoids guessing: an SGDB game id the source already knows wins; failing that
a Steam appid maps exactly; a title search is accepted only on an exact (normalized)
name match. No match means no SGDB art, never the wrong game's art. How a plugin
gets those ids out of its own server's metadata is the plugin's business.
"""

from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Hashable

from . import net
from .net import Image, PluginError

API = "https://www.steamgriddb.com/api/v2"
KEY_PAGE = "https://www.steamgriddb.com/profile/preferences/api"
TIMEOUT = 15.0
MAX_IMAGE_BYTES = 25 * 1024 * 1024

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


def _digits(v: Any) -> int | None:
    s = str(v).strip() if v is not None else ""
    return int(s) if s.isdigit() and int(s) > 0 else None


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
            "User-Agent": net.user_agent(), "Accept": "application/json", "Authorization": f"Bearer {self.key}"})
        try:
            with net.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise PluginError("SteamGridDB rejected the API key", status=401, code="sgdb_key") from None
            if e.code == 404:
                return None
            raise PluginError(f"SteamGridDB error {e.code}", status=e.code, code="sgdb_error") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise PluginError(f"Can't reach SteamGridDB: {getattr(e, 'reason', e)}", code="sgdb_unreachable") from None
        except ValueError:
            raise PluginError("Unexpected response from SteamGridDB", code="sgdb_error") from None
        if not isinstance(body, dict) or not body.get("success"):
            return None
        return body.get("data")

    def validate(self) -> None:
        """Raises PluginError(code='sgdb_key') if the key is wrong."""
        if not self.key:
            raise PluginError("SteamGridDB API key is empty", code="sgdb_key")
        self._get("/search/autocomplete/" + urllib.parse.quote("portal"))

    def resolve(self, title: str = "", sgdb_id: Any = None, steam_appid: Any = None) -> int | None:
        """SGDB game id, or None. Uses the first of: a known SGDB id, a Steam appid, an exact title."""
        known = _digits(sgdb_id)
        if known:
            return known
        appid = _digits(steam_appid)
        if appid:
            data = self._get(f"/games/steam/{appid}")
            if isinstance(data, dict) and data.get("id"):
                return int(data["id"])
        title = (title or "").strip()
        want = normalize_title(title)
        if not want:
            return None
        results = [r for r in self._get("/search/autocomplete/" + urllib.parse.quote(title, safe="")) or []
                   if isinstance(r, dict) and r.get("id")]
        for r in results:
            if normalize_title(r.get("name") or "") == want:
                return int(r["id"])
        # "AM2R: Return of Samus" is listed as "AM2R". Accept the base title only when it is
        # the sole result, so "Batman: Arkham Asylum" can't land on some other "Batman".
        base = normalize_title(re.split(r":| - | – ", title, maxsplit=1)[0])
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
        self._ids: dict[Hashable, int | None] = {}
        self._lock = threading.Lock()

    def assets_for(self, client: SgdbClient, key: Hashable, title: str = "",
                   sgdb_id: Any = None, steam_appid: Any = None) -> dict:
        """``key`` identifies the game in the plugin's own source (its game/ROM id)."""
        with self._lock:
            known = key in self._ids
            gid = self._ids.get(key)
        if not known:
            gid = client.resolve(title, sgdb_id=sgdb_id, steam_appid=steam_appid)
            with self._lock:
                self._ids[key] = gid
        return client.assets(gid) if gid else {}


def fetch_image(url: str, timeout: float = 30.0) -> Image:
    """Download a public SGDB CDN image (no API key is sent)."""
    if not is_sgdb_image_url(url):
        raise PluginError(f"Refusing to fetch non-SteamGridDB URL: {url}", code="bad_image")
    req = urllib.request.Request(url, headers={"User-Agent": net.user_agent(), "Accept": "image/*"})
    try:
        with net.urlopen(req, timeout=timeout) as resp:
            data = resp.read(MAX_IMAGE_BYTES + 1)
            ctype = resp.headers.get_content_type() or "application/octet-stream"
    except urllib.error.HTTPError as e:
        raise PluginError(f"SteamGridDB image error {e.code}", status=e.code, code="sgdb_error") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise PluginError(f"Can't reach SteamGridDB: {getattr(e, 'reason', e)}", code="sgdb_unreachable") from None
    if len(data) > MAX_IMAGE_BYTES:
        raise PluginError("SteamGridDB image is too large", code="bad_image")
    return Image(data, ctype)


def art_plan(own: dict, sgdb: dict, square: bool = False) -> dict:
    """Pick one URL per Steam slot: {capsule, wide, hero, logo}.

    ``own`` is the source server's art as {capsule, wide, hero} (any may be None). Its
    capsule wins the portrait slot (it's what the user curated); SGDB fills the slots the
    source has nothing sized for. With ``square`` the capsule is SGDB's square grid
    instead, falling back to the usual poster."""
    return {
        "capsule": (square and sgdb.get("square")) or own.get("capsule") or sgdb.get("grid"),
        "wide": sgdb.get("wide") or own.get("wide"),
        "hero": sgdb.get("hero") or own.get("hero"),
        "logo": sgdb.get("logo"),
    }
