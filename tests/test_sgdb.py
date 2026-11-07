"""Gameyfin's mapping onto common/sgdb.py (the lookup itself is tested in decky-common)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))

from gameyfin import sgdb  # noqa: E402
from gameyfin.client import GameyfinError  # noqa: E402
from gameyfin.common.net import PluginError  # noqa: E402


class FakeClient:
    def __init__(self):
        self.calls = []

    def resolve(self, title="", sgdb_id=None, steam_appid=None):
        self.calls.append((title, sgdb_id, steam_appid))
        return 42 if title else None

    def assets(self, gid):
        return {"grid": f"G{gid}"}


class LookupTests(unittest.TestCase):
    def test_external_ids(self):
        game = {"id": "1", "title": "AI Limit", "externalIds": [
            {"provider": "org.gameyfin.plugins.metadata.steam", "id": "2407270"},
            {"provider": "org.gameyfin.plugins.metadata.steamgriddb", "id": "5441889"}]}
        self.assertEqual(sgdb.lookup(game), {"title": "AI Limit", "sgdb_id": "5441889", "steam_appid": "2407270"})
        self.assertEqual(sgdb.lookup({"id": "2"}), {"title": "", "sgdb_id": None, "steam_appid": None})

    def test_resolver_keyed_by_game_id(self):
        c, r = FakeClient(), sgdb.SgdbResolver()
        self.assertEqual(sgdb.assets_for(r, c, {"id": 7, "title": "X"}), {"grid": "G42"})
        sgdb.assets_for(r, c, {"id": 7, "title": "X"})
        self.assertEqual(len(c.calls), 1)

    def test_errors_are_one_type(self):
        self.assertIs(GameyfinError, PluginError)
        with self.assertRaises(GameyfinError):
            sgdb.fetch_image("https://example.com/a.png")


class ArtPlanTests(unittest.TestCase):
    GF = {"cover": {"url": "/v1/c"}, "header": {"url": "/v1/h"}, "images": [{"url": "/v1/i0"}]}
    SG = {"grid": "G", "wide": "W", "hero": "H", "logo": "L"}

    def test_gameyfin_cover_first_sgdb_for_the_rest(self):
        self.assertEqual(sgdb.art_plan(self.GF, self.SG), {"capsule": "/v1/c", "wide": "W", "hero": "H", "logo": "L"})

    def test_no_sgdb_matches_old_behaviour(self):
        self.assertEqual(sgdb.art_plan(self.GF, {}),
                         {"capsule": "/v1/c", "wide": "/v1/h", "hero": "/v1/h", "logo": None})
        self.assertEqual(sgdb.art_plan({"images": [{"url": "/v1/i0"}]}, {}),
                         {"capsule": None, "wide": None, "hero": "/v1/i0", "logo": None})

    def test_square_covers(self):
        self.assertEqual(sgdb.art_plan(self.GF, {**self.SG, "square": "S"}, square=True)["capsule"], "S")
        self.assertEqual(sgdb.art_plan(self.GF, {**self.SG, "square": "S"})["capsule"], "/v1/c")
        self.assertEqual(sgdb.art_plan(self.GF, self.SG, square=True)["capsule"], "/v1/c")  # no square: poster

    def test_sgdb_fills_missing_cover(self):
        self.assertEqual(sgdb.art_plan({}, self.SG)["capsule"], "G")


if __name__ == "__main__":
    unittest.main()
