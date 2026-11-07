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
from .exes import LINUX, WINDOWS, find_executables, is_ambiguous, is_windows_exe, preferred_kind, restore_exec_bits
from .installer import Cancelled, install


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


def _load_token(spec: dict) -> str:
    if spec.get("settings_path"):
        with open(spec["settings_path"], encoding="utf-8") as f:
            return json.load(f).get("token", "")
    return os.environ.get("GAMEYFIN_TOKEN", "")


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
        client = GameyfinClient(spec["server_url"], _load_token(spec))
        game = client.get_game(spec["game_id"])
        rep.update(title=game.get("title") or spec.get("title"))
        res = install(client, game, spec["dest_root"], spec["job_id"], rep.progress, cancelled,
                      provider=spec.get("provider"), install_dir=spec.get("install_dir"))
        cands = find_executables(res.install_dir, game.get("title") or "",
                                 prefer=preferred_kind(game.get("platforms")))
        ambiguous = is_ambiguous(cands)
        # Update: keep the exe the user already chose if the new build still has it.
        keep = spec.get("exe")
        if keep and os.path.isfile(os.path.join(res.install_dir, keep)):
            # find_executables may have filtered it out (depth, exclude list), so synthesise if needed.
            first = [c for c in cands if c["path"] == keep] or [
                {"path": keep, "size": os.path.getsize(os.path.join(res.install_dir, keep)), "depth": 0,
                 "name_match": True, "kind": WINDOWS if is_windows_exe(keep) else LINUX}]
            cands = first + [c for c in cands if c["path"] != keep]
            ambiguous = False
        if any(c["kind"] == LINUX for c in cands):
            restore_exec_bits(res.install_dir)  # Gameyfin's zips drop Unix modes
        rep.update(phase="done", install_dir=res.install_dir, exe_candidates=cands[:12],
                   exe_ambiguous=ambiguous, installed_bytes=res.installed_bytes,
                   server_file_size=game.get("fileSize"),
                   done=res.installed_bytes, total=res.installed_bytes, speed=0, finished_at=time.time())
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
