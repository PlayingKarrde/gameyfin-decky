import json
import os
import sys
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))

from gameyfin import sgdb  # noqa: E402
from gameyfin.client import GameyfinError  # noqa: E402

GOOD_KEY = "k" * 32


def img(url, w, h, score=0):
    return {"id": url, "url": f"https://cdn2.steamgriddb.com/{url}.png", "width": w, "height": h, "score": score}


ROUTES = {
    "/games/steam/2407270": {"success": True, "data": {"id": 777, "name": "AI Limit"}},
    "/search/autocomplete/AM2R%3A%20Return%20of%20Samus": {"success": True, "data": [
        {"id": 1, "name": "AM2R"}, {"id": 42, "name": "AM2R - Return of Samus"}]},
    "/search/autocomplete/Unknown%20Game": {"success": True, "data": [{"id": 5, "name": "Unknown Game 2"}]},
    "/search/autocomplete/Metroid%20II%3A%20Remake": {"success": True, "data": [{"id": 8, "name": "Metroid II"}]},
    "/search/autocomplete/Batman%3A%20Arkham%20Asylum": {"success": True, "data": [
        {"id": 9, "name": "Batman"}, {"id": 10, "name": "Batman: Arkham Asylum GOTY"}]},
    "/search/autocomplete/portal": {"success": True, "data": [{"id": 1, "name": "Portal"}]},
    "/grids/game/42": {"success": True, "data": [
        img("p-low", 600, 900, 1), img("p-high", 600, 900, 9), img("w-small", 460, 215, 50), img("w-big", 920, 430, 2),
        img("s-512", 512, 512, 7), img("s-1024", 1024, 1024, 1)]},
    "/heroes/game/42": {"success": True, "data": [img("h1", 1920, 620, 3), img("h2", 3840, 1240, 4)]},
    "/logos/game/42": {"success": True, "data": []},
}


class Handler(BaseHTTPRequestHandler):
    seen: list = []

    def log_message(self, *a):
        pass

    def do_GET(self):  # noqa: N802
        path, _, query = self.path.partition("?")
        Handler.seen.append((path, urllib.parse.parse_qs(query)))
        if self.headers.get("Authorization") != f"Bearer {GOOD_KEY}":
            return self._send(401, {"success": False, "errors": ["unauthorized"]})
        body = ROUTES.get(path)
        self._send(200 if body else 404, body or {"success": False, "errors": ["not found"]})

    def _send(self, status, obj):
        raw = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class SgdbTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        Handler.seen.clear()
        self.c = sgdb.SgdbClient(GOOD_KEY, base=self.base)

    def test_validate(self):
        self.c.validate()
        with self.assertRaises(GameyfinError) as cm:
            sgdb.SgdbClient("wrong", base=self.base).validate()
        self.assertEqual(cm.exception.code, "sgdb_key")
        with self.assertRaises(GameyfinError):
            sgdb.SgdbClient("", base=self.base).validate()

    def test_resolve_prefers_gameyfin_sgdb_id(self):
        game = {"id": "1", "title": "x", "externalIds": [
            {"provider": "org.gameyfin.plugins.metadata.steam", "id": "2407270"},
            {"provider": "org.gameyfin.plugins.metadata.steamgriddb", "id": "5441889"}]}
        self.assertEqual(self.c.resolve(game), 5441889)
        self.assertEqual(Handler.seen, [])  # no request needed

    def test_resolve_via_steam_appid(self):
        game = {"id": "1", "title": "AI Limit", "externalIds": [
            {"provider": "org.gameyfin.plugins.metadata.steam", "id": "2407270"}]}
        self.assertEqual(self.c.resolve(game), 777)

    def test_resolve_by_exact_title_only(self):
        self.assertEqual(self.c.resolve({"id": "2", "title": "AM2R: Return of Samus"}), 42)
        self.assertIsNone(self.c.resolve({"id": "3", "title": "Unknown Game"}))

    def test_resolve_base_title_only_when_sole_result(self):
        self.assertEqual(self.c.resolve({"id": "4", "title": "Metroid II: Remake"}), 8)
        self.assertIsNone(self.c.resolve({"id": "5", "title": "Batman: Arkham Asylum"}))

    def test_assets_pick_top_score_per_slot(self):
        a = self.c.assets(42)
        self.assertEqual(a["grid"], "https://cdn2.steamgriddb.com/p-high.png")
        self.assertEqual(a["wide"], "https://cdn2.steamgriddb.com/w-big.png")  # 920x430 preferred over 460x215
        self.assertEqual(a["square"], "https://cdn2.steamgriddb.com/s-1024.png")
        self.assertEqual(a["hero"], "https://cdn2.steamgriddb.com/h2.png")
        self.assertIsNone(a["logo"])
        _, q = next(s for s in Handler.seen if s[0] == "/grids/game/42")
        self.assertEqual(q["nsfw"], ["false"])
        self.assertEqual(q["types"], ["static"])

    def test_resolver_caches_misses(self):
        r = sgdb.SgdbResolver()
        self.assertEqual(r.assets_for(self.c, {"id": "3", "title": "Unknown Game"}), {})
        n = len(Handler.seen)
        r.assets_for(self.c, {"id": "3", "title": "Unknown Game"})
        self.assertEqual(len(Handler.seen), n)

    def test_image_url_allowlist(self):
        self.assertTrue(sgdb.is_sgdb_image_url("https://cdn2.steamgriddb.com/grid/a.png"))
        self.assertFalse(sgdb.is_sgdb_image_url("http://cdn2.steamgriddb.com/grid/a.png"))
        self.assertFalse(sgdb.is_sgdb_image_url("https://steamgriddb.com.evil.net/a.png"))
        self.assertFalse(sgdb.is_sgdb_image_url("/v1/games/2/images/3"))
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
