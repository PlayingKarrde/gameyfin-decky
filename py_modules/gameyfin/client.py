"""Minimal Gameyfin v1 API client.

Stdlib only (urllib) so it runs inside Decky's bundled Python *and* in the
standalone download worker / CLI without vendoring anything. All calls are
blocking; async callers should wrap them in ``asyncio.to_thread``.
"""

from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

USER_AGENT = "gameyfin-decky/0.1"
DEFAULT_TIMEOUT = 15.0


class GameyfinError(Exception):
    """API or transport failure, with a message fit to show the user."""

    def __init__(self, message: str, status: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code

    def to_dict(self) -> dict:
        return {"message": str(self), "status": self.status, "code": self.code}


def normalize_base_url(url: str) -> str:
    """'192.168.1.5:8080/' -> 'http://192.168.1.5:8080'. Tolerates CRLF/whitespace."""
    url = (url or "").strip()
    if not url:
        raise GameyfinError("Server URL is empty")
    if "://" not in url:
        url = "http://" + url
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise GameyfinError(f"Invalid server URL: {url}")
    return url.rstrip("/")


@dataclass
class Image:
    data: bytes
    content_type: str


class GameyfinClient:
    def __init__(self, base_url: str, token: str, timeout: float = DEFAULT_TIMEOUT):
        self.base_url = normalize_base_url(base_url)
        self.token = (token or "").strip()
        self.timeout = timeout

    # ---- transport -------------------------------------------------------

    def _url(self, path: str, params: dict[str, Any] | None = None) -> str:
        url = self.base_url + path
        if params:
            clean = {k: v for k, v in params.items() if v is not None and v != ""}
            if clean:
                url += "?" + urllib.parse.urlencode(clean, doseq=True)
        return url

    def _open(self, path: str, params: dict[str, Any] | None = None, auth: bool = True):
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json, image/*;q=0.9, */*;q=0.5"}
        if auth:
            if not self.token:
                raise GameyfinError("No API token configured", code="no_token")
            headers["X-API-Key"] = self.token
        req = urllib.request.Request(self._url(path, params), headers=headers)
        try:
            return urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            raise self._http_error(e) from None
        except urllib.error.URLError as e:
            raise GameyfinError(f"Can't reach server: {e.reason}", code="unreachable") from None
        except TimeoutError:
            raise GameyfinError("Server timed out", code="timeout") from None
        except OSError as e:
            raise GameyfinError(f"Network error: {e}", code="network") from None

    @staticmethod
    def _http_error(e: urllib.error.HTTPError) -> GameyfinError:
        # Gameyfin returns RFC 7807 problem+json: {title, detail, status, code}
        detail = None
        code = None
        try:
            try:
                raw = e.read()
            except http.client.IncompleteRead as ir:
                # Gameyfin 2.6.0 /v1 download errors keep the zip's Content-Length.
                raw = ir.partial
            body = json.loads(raw.decode("utf-8", "replace"))
            detail = body.get("detail") or body.get("title")
            code = body.get("code")
        except Exception:
            pass
        if e.code == 401:
            msg = "API token was rejected (invalid, expired or revoked)"
        elif e.code == 403:
            msg = f"API token lacks permission: {detail}" if detail else "API token lacks permission"
        elif e.code == 404:
            msg = detail or "Not found"
        else:
            msg = f"Server error {e.code}" + (f": {detail}" if detail else "")
        return GameyfinError(msg, status=e.code, code=code)

    def _json(self, path: str, params: dict[str, Any] | None = None, auth: bool = True) -> Any:
        with self._open(path, params, auth) as resp:
            raw = resp.read()
        try:
            return json.loads(raw)
        except ValueError:
            raise GameyfinError(f"Unexpected non-JSON response from {path}", code="bad_response") from None

    # ---- endpoints -------------------------------------------------------

    def instance(self) -> dict:
        return self._json("/v1/instance")

    def me(self) -> dict:
        """Only works with personal access tokens (service keys get 403)."""
        return self._json("/v1/me")

    def list_games(
        self,
        page: int = 0,
        size: int = 50,
        q: str | None = None,
        sort: str | None = "title,asc",
        library_id: str | None = None,
        platform: str | None = None,
    ) -> dict:
        """Returns PageV1<GameV1>: {items, page, size, totalElements}."""
        return self._json(
            "/v1/games",
            {"page": page, "size": size, "q": q, "sort": sort, "libraryId": library_id, "platform": platform},
        )

    def get_game(self, game_id: str) -> dict:
        return self._json(f"/v1/games/{urllib.parse.quote(str(game_id), safe='')}")

    def download_providers(self) -> list[dict]:
        return self._json("/v1/download-providers")

    def open_download(self, game_id: str, provider: str, timeout: float = 60.0):
        """Open the download stream. Returns the raw HTTP response (caller must close).

        The body is either the file itself (octet-stream) or a JSON
        ``{kind: "link", url}`` descriptor; inspect Content-Type to tell.

        Gameyfin 2.6.0 bug: ``/v1/games/{id}/download`` returns 500 for every file
        download (its controller declares ``ResponseEntity<*>``, so Spring never
        uses the streaming handler). On a 500 we fall back to the web UI endpoint
        ``/download/{id}``, which works when the server allows public access.
        """
        saved, self.timeout = self.timeout, timeout  # per-read socket timeout for big streams
        try:
            try:
                return self._open(
                    f"/v1/games/{urllib.parse.quote(str(game_id), safe='')}/download", {"provider": provider}
                )
            except GameyfinError as e:
                if e.status != 500:
                    raise
            return self._open_web_download(game_id, provider)
        finally:
            self.timeout = saved

    def _open_web_download(self, game_id: str, provider: str):
        try:
            resp = self._open(f"/download/{urllib.parse.quote(str(game_id), safe='')}", {"provider": provider},
                              auth=False)
        except GameyfinError as e:
            if e.status in (401, 403):
                raise self._web_download_unavailable() from None
            raise
        if resp.headers.get_content_type() != "application/octet-stream":
            resp.close()  # login page / SPA shell: public access is off
            raise self._web_download_unavailable()
        return resp

    @staticmethod
    def _web_download_unavailable() -> GameyfinError:
        return GameyfinError(
            "Gameyfin 2.6.0's API download is broken (server bug). Enable public access in Gameyfin, "
            "or update Gameyfin once it is fixed.", status=500, code="server_download_bug")

    def fetch_image(self, url_or_path: str) -> Image:
        """Fetch an image by its API-relative url (e.g. '/v1/games/2/images/421')."""
        path = url_or_path
        if path.startswith(self.base_url):
            path = path[len(self.base_url):]
        if not path.startswith("/v1/"):
            raise GameyfinError(f"Refusing to fetch non-API image URL: {url_or_path}")
        with self._open(path) as resp:
            ctype = resp.headers.get_content_type() or "application/octet-stream"
            return Image(resp.read(), ctype)

    # ---- composite -------------------------------------------------------

    def test_connection(self) -> dict:
        """Probe exactly what the plugin needs. Works with personal tokens and service keys."""
        result: dict[str, Any] = {"ok": False}
        try:
            result["server_version"] = self.instance().get("version")
        except GameyfinError as e:
            if e.status != 403:  # service key without instance:read — not needed
                raise
            result["server_version"] = None
        page = self.list_games(size=1, sort=None)
        result["game_count"] = page.get("totalElements")
        providers = self.download_providers()
        result["download_providers"] = [p.get("name") or p.get("id") for p in providers]
        try:
            result["username"] = self.me().get("username")
            result["token_kind"] = "personal"
        except GameyfinError as e:
            if e.status != 403:
                raise
            result["username"] = None
            result["token_kind"] = "service"
        result["ok"] = True
        return result
