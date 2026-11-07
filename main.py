import asyncio
import dataclasses
import os
import platform
import threading
from typing import Any, Callable

# decky is injected by Decky Loader at runtime; decky.pyi provides type hints.
import decky

from gameyfin import jobs
from gameyfin.client import GameyfinClient, GameyfinError, normalize_base_url
from gameyfin.exes import ensure_executable, find_executables, is_windows_exe
from gameyfin.installed import InstalledStore, delete_game_dir, delete_prefix, install_targets
from gameyfin.installer import check_space
from gameyfin.pairing import PairingSession
from gameyfin.images import ImageCache
from gameyfin.library import game_detail, page_summary
from gameyfin.settings import Settings, SettingsStore
from gameyfin.status import check_all, files_state

log = decky.logger


def _ok(data: Any = None) -> dict:
    return {"ok": True, "data": data}


def _err(e: Exception) -> dict:
    if isinstance(e, GameyfinError):
        return {"ok": False, "error": e.to_dict()}
    log.exception("Unexpected backend error")
    return {"ok": False, "error": {"message": f"Internal error: {e}", "status": None, "code": "internal"}}


class Plugin:
    store: SettingsStore
    settings: Settings
    images: ImageCache
    installed: InstalledStore
    pairing: PairingSession | None = None
    jobs_root: str
    _install_lock: threading.Lock

    def _client(self) -> GameyfinClient:
        if not self.settings.server_url:
            raise GameyfinError("Server URL not set", code="not_configured")
        if not self.settings.token:
            raise GameyfinError("API token not set", code="not_configured")
        return GameyfinClient(self.settings.server_url, self.settings.token)

    async def _call(self, fn: Callable[[], Any]) -> dict:
        """Run blocking client code off the event loop and wrap the result."""
        try:
            return _ok(await asyncio.to_thread(fn))
        except Exception as e:  # noqa: BLE001 — surfaced to UI via envelope
            return _err(e)

    # ---- diagnostics -------------------------------------------------------

    async def ping(self) -> dict:
        return {"ok": True, "python": platform.python_version(), "user": decky.DECKY_USER}

    # ---- settings ----------------------------------------------------------

    async def get_settings(self) -> dict:
        return _ok(self.settings.public())

    async def save_settings(self, server_url: str, token: str | None = None) -> dict:
        """token=None/'' keeps the existing token (the UI never sees it)."""
        try:
            url = normalize_base_url(server_url)
        except GameyfinError as e:
            return _err(e)
        new_token = (token or "").strip() or self.settings.token
        self.settings = dataclasses.replace(self.settings, server_url=url, token=new_token)
        self.store.save(self.settings)
        log.info("Settings saved (server=%s, token set=%s)", url, bool(new_token))
        return _ok(self.settings.public())

    async def test_connection(self, server_url: str | None = None, token: str | None = None) -> dict:
        """Test given values (unsaved form) falling back to saved ones."""
        url = (server_url or "").strip() or self.settings.server_url
        tok = (token or "").strip() or self.settings.token

        def run():
            if not url:
                raise GameyfinError("Server URL not set", code="not_configured")
            if not tok:
                raise GameyfinError("API token not set", code="not_configured")
            return GameyfinClient(url, tok).test_connection()

        res = await self._call(run)
        log.info("Test connection: %s", res if res["ok"] else res["error"])
        return res

    # ---- phone pairing -----------------------------------------------------

    def _pair_submit(self, server_url: str, token: str) -> str:
        """Runs on the pairing server's thread. Validate first, then save."""
        url = normalize_base_url(server_url)
        info = GameyfinClient(url, token).test_connection()
        self.settings = dataclasses.replace(self.settings, server_url=url, token=token)
        self.store.save(self.settings)
        log.info("Paired via phone (server=%s)", url)
        who = f" as {info['username']}" if info.get("username") else ""
        return f"Connected to Gameyfin{who}."

    async def start_pairing(self) -> dict:
        def run():
            if self.pairing:
                self.pairing.stop()
            self.pairing = PairingSession(self.settings.server_url, self._pair_submit).start()
            log.info("Pairing server listening on %s:%s", self.pairing.ip, self.pairing.port)
            return self.pairing.status()
        return await self._call(run)

    async def get_pairing_status(self) -> dict:
        if not self.pairing:
            return _ok({"state": "stopped"})
        st = self.pairing.status()
        if st["state"] == "done":
            st["settings"] = self.settings.public()
        return _ok(st)

    async def stop_pairing(self) -> dict:
        if self.pairing:
            self.pairing.stop()
        return _ok(None)

    # ---- library -----------------------------------------------------------

    async def list_games(self, page: int = 0, size: int = 50, query: str = "", library_id: str = "") -> dict:
        size = max(1, min(int(size), 100))
        return await self._call(
            lambda: page_summary(self._client().list_games(page=int(page), size=size, q=(query or "").strip() or None,
                                                           library_id=library_id or None))
        )

    async def list_libraries(self) -> dict:
        """[{id, name}]; empty if the token can't read libraries (e.g. a service key without the scope)."""
        def run():
            try:
                page = self._client().list_libraries()
            except GameyfinError as e:
                if e.status == 403:
                    return []
                raise
            return [{"id": str(lib.get("id")), "name": lib.get("name") or f"Library {lib.get('id')}"}
                    for lib in page.get("items") or []]
        return await self._call(run)

    async def get_game(self, game_id: str) -> dict:
        return await self._call(lambda: game_detail(self._client().get_game(game_id)))

    async def get_image(self, image_url: str) -> dict:
        """{thumb: dataURL} if cached, else {content_type, size, chunks} for chunked fetch."""
        return await self._call(lambda: self.images.describe(self._client(), image_url))

    async def get_image_chunk(self, image_url: str, index: int) -> dict:
        return await self._call(lambda: self.images.chunk(image_url, index))

    async def save_thumbnail(self, image_url: str, data_url: str) -> dict:
        return await self._call(lambda: self.images.save_thumbnail(image_url, data_url))

    async def get_artwork(self, image_url: str) -> dict:
        """Full-size original as {content_type, size, chunks}; fetch slices with get_image_chunk."""
        return await self._call(lambda: self.images.describe_original(self._client(), image_url))

    # ---- install -----------------------------------------------------------

    def _home(self) -> str:
        return decky.DECKY_USER_HOME

    def _steam_root(self) -> str:
        for p in (os.path.join(self._home(), ".local/share/Steam"), os.path.join(self._home(), ".steam/steam")):
            if os.path.isdir(os.path.join(p, "steamapps")):
                return p
        return os.path.join(self._home(), ".local/share/Steam")

    async def get_install_targets(self) -> dict:
        return await self._call(lambda: install_targets(self._home(), self.settings.custom_install_dir))

    async def set_custom_install_dir(self, path: str) -> dict:
        path = (path or "").strip()
        if path and not os.path.isabs(path):
            return _err(GameyfinError("Custom folder must be an absolute path", code="bad_path"))
        self.settings.custom_install_dir = os.path.normpath(path) if path else ""
        self.store.save(self.settings)
        return _ok(self.settings.public())

    def _launch_job(self, game_id: str, dest_root: str, extra: dict | None = None) -> dict:
        game = self._client().get_game(game_id)
        os.makedirs(dest_root, exist_ok=True)
        check_space(dest_root, game.get("fileSize"))
        # Check-then-create under a lock: two quick presses would otherwise both pass
        # the check and start two workers writing the same folder.
        with self._install_lock:
            active = [j for j in jobs.list_jobs(self.jobs_root)
                      if str(j.get("game_id")) == str(game_id) and j.get("phase") not in jobs.TERMINAL]
            if active:
                raise GameyfinError("This game is already being installed", code="busy")
            job_dir = jobs.create_job(self.jobs_root, {
                "game_id": str(game_id), "title": game.get("title"), "dest_root": dest_root,
                "server_url": self.settings.server_url, "file_size": game.get("fileSize"),
                "settings_path": self.store.path,
                "innoextract": os.path.join(decky.DECKY_PLUGIN_DIR, "bin", "innoextract"),
                **(extra or {}),
            })
        how = jobs.launch_worker(job_dir, os.path.join(decky.DECKY_PLUGIN_DIR, "py_modules"))
        log.info("%s %s (%s) -> %s via %s", (extra or {}).get("kind", "install").capitalize(), game_id,
                 game.get("title"), dest_root, how)
        return {"job_id": os.path.basename(job_dir)}

    async def start_install(self, game_id: str, target_path: str) -> dict:
        def run():
            allowed = {t["path"] for t in install_targets(self._home(), self.settings.custom_install_dir)}
            if target_path not in allowed:
                raise GameyfinError("Unknown install location", code="bad_target")
            return self._launch_job(game_id, target_path)
        return await self._call(run)

    async def update_game(self, game_id: str) -> dict:
        """Re-download into the same folder, keeping the shortcut, prefix and chosen exe."""
        def run():
            rec = self.installed.get(game_id)
            if not rec or not rec.get("install_dir"):
                raise GameyfinError("Game is not installed", code="not_found")
            if files_state(rec["install_dir"], game_id) == "unmarked":
                raise GameyfinError("The install folder no longer looks like this game; reinstall instead",
                                    code="unsafe_delete")
            return self._launch_job(game_id, os.path.dirname(rec["install_dir"].rstrip("/")),
                                    {"kind": "update", "install_dir": rec["install_dir"], "exe": rec.get("exe")})
        return await self._call(run)

    async def get_install_status(self) -> dict:
        """Per installed game: {game_id, files, update_available, server_missing, server_size, summary, error}."""
        def run():
            records = list(self.installed.load().values())
            try:
                client = self._client()
                get_game = client.get_game
            except GameyfinError:  # not configured: report local file state only
                get_game = None
            return check_all(get_game, records)
        return await self._call(run)

    async def forget_installed(self, game_id: str) -> dict:
        """Drop the record but leave any files on disk (for moved, missing or unmarked folders)."""
        def run():
            rec = self.installed.remove(game_id)
            log.info("Forgot install record %s (%s)", game_id, (rec or {}).get("title"))
        return await self._call(run)

    async def get_jobs(self) -> dict:
        return await self._call(lambda: jobs.list_jobs(self.jobs_root))

    async def cancel_install(self, job_id: str) -> dict:
        def run():
            jd = os.path.join(self.jobs_root, os.path.basename(job_id))
            if not os.path.isdir(jd):
                raise GameyfinError("No such job", code="not_found")
            jobs.request_cancel(jd)
        return await self._call(run)

    async def dismiss_job(self, job_id: str) -> dict:
        return await self._call(lambda: jobs.remove_job(self.jobs_root, job_id))

    async def list_executables(self, install_dir: str, title: str = "") -> dict:
        return await self._call(lambda: find_executables(install_dir, title)[:30])

    async def register_installed(self, game_id: str, record: dict) -> dict:
        """Merge into the record (only keys present are changed). Called after the shortcut exists."""
        keep = ("title", "install_dir", "exe", "appid", "size", "compat_tool", "server_file_size", "launch_args",
                "work_dir")

        def run():
            rec = self.installed.put(game_id, {k: record[k] for k in keep if k in record})
            if rec.get("exe") and rec.get("install_dir") and not is_windows_exe(rec["exe"]):
                ensure_executable(rec["install_dir"], rec["exe"])  # a hand-picked native launcher
            return rec
        return await self._call(run)

    async def get_installed(self) -> dict:
        return await self._call(lambda: list(self.installed.load().values()))

    async def uninstall_game(self, game_id: str, remove_prefix: bool = False) -> dict:
        """Frontend removes the Steam shortcut first; this deletes files and the record."""
        def run():
            rec = self.installed.get(game_id)
            if not rec:
                raise GameyfinError("Game is not installed", code="not_found")
            delete_game_dir(rec["install_dir"], game_id)
            prefix_removed = bool(remove_prefix and rec.get("appid")) and delete_prefix(self._steam_root(),
                                                                                         rec["appid"])
            self.installed.remove(game_id)
            log.info("Uninstalled %s (%s), prefix removed=%s", game_id, rec.get("title"), prefix_removed)
            return {"prefix_removed": prefix_removed}
        return await self._call(run)

    async def prefix_exists(self, appid: int) -> dict:
        return await self._call(lambda: os.path.isdir(
            os.path.join(self._steam_root(), "steamapps", "compatdata", str(int(appid)))))

    # ---- lifecycle ---------------------------------------------------------

    async def _main(self):
        self.store = SettingsStore(decky.DECKY_PLUGIN_SETTINGS_DIR)
        self.settings = self.store.load()
        self.images = ImageCache(decky.DECKY_PLUGIN_RUNTIME_DIR)
        self.installed = InstalledStore(decky.DECKY_PLUGIN_SETTINGS_DIR)
        self.jobs_root = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "jobs")
        self._install_lock = threading.Lock()
        os.makedirs(self.jobs_root, exist_ok=True)
        log.info("Gameyfin plugin loaded (configured=%s)", bool(self.settings.server_url and self.settings.token))

    async def _unload(self):
        if self.pairing:
            self.pairing.stop()
        log.info("Gameyfin plugin unloading")

    async def _uninstall(self):
        log.info("Gameyfin plugin uninstalled")
