"""Shape Gameyfin API objects into small payloads for the frontend."""

from __future__ import annotations

from typing import Any


def _image_url(img: Any) -> str | None:
    if isinstance(img, dict):
        return img.get("url")
    return None


def game_summary(g: dict) -> dict:
    """Grid-sized view of a GameV1 (keeps bridge payloads small)."""
    return {
        "id": str(g.get("id")),
        "title": g.get("title") or "(untitled)",
        "platforms": g.get("platforms") or [],
        "release": g.get("release"),
        "file_size": g.get("fileSize"),
        "cover": _image_url(g.get("cover")),
    }


def game_detail(g: dict) -> dict:
    d = game_summary(g)
    d.update(
        {
            "summary": g.get("summary"),
            "header": _image_url(g.get("header")),
            "images": [i.get("url") for i in (g.get("images") or []) if i.get("url")],
            "genres": g.get("genres") or [],
            "developers": g.get("developers") or [],
            "publishers": g.get("publishers") or [],
            "critic_rating": g.get("criticRating"),
            "user_rating": g.get("userRating"),
        }
    )
    return d


def page_summary(page: dict) -> dict:
    return {
        "items": [game_summary(g) for g in page.get("items") or []],
        "page": page.get("page", 0),
        "size": page.get("size", 0),
        "total": page.get("totalElements", 0),
    }
