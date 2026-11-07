"""SteamGridDB for Gameyfin games: the lookup itself lives in common/sgdb.py; this maps
a Gameyfin GameV1 onto it.

Gameyfin's own SteamGridDB metadata plugin usually stores the SGDB game id in
``externalIds``; failing that its Steam appid maps exactly; else the title.
"""

from __future__ import annotations

from .common import sgdb as _sgdb
from .common.sgdb import KEY_PAGE, SgdbClient, SgdbResolver, fetch_image, is_sgdb_image_url  # noqa: F401

_PROVIDER_SGDB = "steamgriddb"
_PROVIDER_STEAM = "steam"


def external_id(game: dict, provider: str) -> str | None:
    """externalIds is [{provider: 'org.gameyfin.plugins.metadata.<name>', id}]."""
    for x in game.get("externalIds") or []:
        if isinstance(x, dict) and str(x.get("provider", "")).rsplit(".", 1)[-1] == provider and x.get("id"):
            return str(x["id"])
    return None


def lookup(game: dict) -> dict:
    """Keyword args for SgdbClient.resolve / SgdbResolver.assets_for."""
    return {"title": game.get("title") or "", "sgdb_id": external_id(game, _PROVIDER_SGDB),
            "steam_appid": external_id(game, _PROVIDER_STEAM)}


def resolve(client: SgdbClient, game: dict) -> int | None:
    return client.resolve(**lookup(game))


def assets_for(resolver: SgdbResolver, client: SgdbClient, game: dict) -> dict:
    return resolver.assets_for(client, str(game.get("id")), **lookup(game))


def own_art(game: dict) -> dict:
    """Gameyfin's art as {capsule, wide, hero}: the cover, the header, the first screenshot."""
    images = [i.get("url") for i in game.get("images") or [] if isinstance(i, dict) and i.get("url")]
    cover = (game.get("cover") or {}).get("url") if isinstance(game.get("cover"), dict) else None
    header = (game.get("header") or {}).get("url") if isinstance(game.get("header"), dict) else None
    return {"capsule": cover, "wide": header, "hero": header or (images[0] if images else None)}


def art_plan(game: dict, sgdb: dict, square: bool = False) -> dict:
    """Gameyfin's cover wins the portrait capsule; SGDB fills the rest (see common.sgdb.art_plan)."""
    return _sgdb.art_plan(own_art(game), sgdb, square=square)
