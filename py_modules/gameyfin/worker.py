"""Install worker: ``python3 -m gameyfin.worker <job_dir>``.

Runs outside Decky (system python, own systemd --user unit). Reads job.json,
reports progress to state.json, honours the cancel flag and SIGTERM.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
import traceback

from . import jobs
from .client import GameyfinClient, GameyfinError
from .exes import (LINUX, WINDOWS, find_executables, gog_play_task, is_ambiguous, is_windows_exe, preferred_kind,
                   restore_exec_bits)
from .deps import find_redists, write_wrapper
from .installer import Cancelled, install
from .installers import InstallerError, find_installers, install_from_installers


class Reporter:
    """Throttled state writer with a smoothed speed estimate."""

    def __init__(self, job_dir: str, base: dict):
        self.job_dir = job_dir
        self.state = dict(base)
        self._last_t = time.monotonic()
        self._last_done = 0
        self._last_phase = None
        self._speed = 0.0

    def update(self, **fields) -> None:
        self.state.update(fields)
        jobs.write_state(self.job_dir, self.state)

    def progress(self, phase: str, done: int, total: int | None) -> None:
        now = time.monotonic()
        if phase != self._last_phase:
            self._last_phase, self._last_done, self._last_t, self._speed = phase, done, now, 0.0
        dt = now - self._last_t
        if dt >= 0.5:
            inst = (done - self._last_done) / dt
            self._speed = inst if self._speed == 0 else 0.7 * self._speed + 0.3 * inst
            self._last_t, self._last_done = now, done
        self.update(phase=phase, done=done, total=total, speed=round(self._speed))


def _load_settings(spec: dict) -> dict:
    if spec.get("settings_path"):
        with open(spec["settings_path"], encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    return {"token": os.environ.get("GAMEYFIN_TOKEN", "")}


def run(job_dir: str) -> int:
    spec = jobs.read_spec(job_dir)
    rep = Reporter(job_dir, {
        "job_id": spec["job_id"], "game_id": spec["game_id"], "title": spec.get("title"),
        "dest_root": spec["dest_root"], "pid": os.getpid(), "started_at": time.time(),
        "phase": "starting", "done": 0, "total": spec.get("file_size"), "kind": spec.get("kind", "install"),
    })
    rep.update()

    cancel = {"flag": False}
    signal.signal(signal.SIGTERM, lambda *_: cancel.__setitem__("flag", True))
    cancelled = lambda: cancel["flag"] or jobs.cancel_requested(job_dir)  # noqa: E731

    try:
        settings = _load_settings(spec)
        client = GameyfinClient(spec["server_url"], settings.get("token", ""))
        game = client.get_game(spec["game_id"])
        rep.update(title=game.get("title") or spec.get("title"))
        res = install(client, game, spec["dest_root"], spec["job_id"], rep.progress, cancelled,
                      provider=spec.get("provider"), install_dir=spec.get("install_dir"))
        installed_bytes = res.installed_bytes
        warnings: list[str] = []
        setups = find_installers(res.install_dir)
        if setups and spec.get("innoextract") and os.path.isfile(spec["innoextract"]):
            # GOG-style installers (base game + DLC): unpack into a normal game folder.
            try:
                inst = install_from_installers(spec["innoextract"], res.install_dir, setups, rep.progress, cancelled)
            except InstallerError as e:
                raise GameyfinError(f"Couldn't unpack the installer: {e}", code="installer_failed") from None
            installed_bytes, warnings = inst.installed_bytes, inst.warnings
        cands = find_executables(res.install_dir, game.get("title") or "",
                                 prefer=preferred_kind(game.get("platforms")))
        ambiguous = is_ambiguous(cands)
        # GOG builds say exactly what to launch; trust that over our ranking.
        task = gog_play_task(res.install_dir)
        # Update: keep the exe the user already chose if the new build still has it.
        keep = spec.get("exe") or (task and task["path"])
        if keep and os.path.isfile(os.path.join(res.install_dir, keep)):
            # find_executables may have filtered it out (depth, exclude list), so synthesise if needed.
            first = [c for c in cands if c["path"] == keep] or [
                {"path": keep, "size": os.path.getsize(os.path.join(res.install_dir, keep)), "depth": 0,
                 "name_match": True, "kind": WINDOWS if is_windows_exe(keep) else LINUX}]
            cands = first + [c for c in cands if c["path"] != keep]
            ambiguous = False
        launch = {}
        if task and cands and cands[0]["path"] == task["path"]:  # its args only fit its own exe
            launch = {"launch_args": task["args"], "work_dir": task["work_dir"]}
        if any(c["kind"] == LINUX for c in cands):
            restore_exec_bits(res.install_dir)  # Gameyfin's zips drop Unix modes
        # Bundled VC++/DirectX/... run in the prefix on first launch (Windows games only).
        deps: dict = {}
        if settings.get("install_deps", True) and any(c["kind"] == WINDOWS for c in cands):
            redists = find_redists(res.install_dir)
            wrapper = write_wrapper(res.install_dir, redists)
            if wrapper:
                deps = {"deps_wrapper": wrapper, "deps": [r["label"] for r in redists]}
        rep.update(phase="done", install_dir=res.install_dir, exe_candidates=cands[:12], **launch, **deps,
                   warnings=warnings,
                   exe_ambiguous=ambiguous, installed_bytes=installed_bytes,
                   server_file_size=game.get("fileSize"),
                   done=installed_bytes, total=installed_bytes, speed=0, finished_at=time.time())
        return 0
    except Cancelled:
        rep.update(phase="cancelled", speed=0, finished_at=time.time())
        return 2
    except GameyfinError as e:
        rep.update(phase="error", error=str(e), error_code=e.code, speed=0, finished_at=time.time())
        return 1
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        rep.update(phase="error", error=f"{type(e).__name__}: {e}", error_code="internal", speed=0,
                   finished_at=time.time())
        return 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python3 -m gameyfin.worker <job_dir>")
    sys.exit(run(sys.argv[1]))
