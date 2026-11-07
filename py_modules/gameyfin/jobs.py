"""Install jobs: one directory per job, shared by the plugin and the worker.

  <jobs_root>/<job_id>/job.json    spec written by the plugin (no secrets)
  <jobs_root>/<job_id>/state.json  progress written atomically by the worker
  <jobs_root>/<job_id>/cancel      presence = cancel requested
  <jobs_root>/<job_id>/worker.log  worker stdout/stderr (fallback launcher only)

The worker runs as its own transient systemd --user unit, so it is not tied to
Decky's process tree and survives plugin reloads and loader restarts.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid

TERMINAL = ("done", "error", "cancelled")
SYSTEM_PYTHON = "/usr/bin/python3"
STALE_AFTER = 30  # seconds without a state update while the pid is gone -> dead


def _write_json(path: str, data: dict, mode: int = 0o600) -> None:
    tmp = f"{path}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def _read_json(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# ---- job lifecycle ---------------------------------------------------------


def create_job(jobs_root: str, spec: dict) -> str:
    job_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    job_dir = os.path.join(jobs_root, job_id)
    os.makedirs(job_dir, mode=0o700)
    _write_json(os.path.join(job_dir, "job.json"), {**spec, "job_id": job_id})
    write_state(job_dir, {"job_id": job_id, "game_id": spec.get("game_id"), "title": spec.get("title"),
                          "phase": "queued", "done": 0, "total": spec.get("file_size"),
                          "kind": spec.get("kind", "install"),
                          "created_at": time.time()})
    return job_dir


def read_spec(job_dir: str) -> dict:
    spec = _read_json(os.path.join(job_dir, "job.json"))
    if spec is None:
        raise FileNotFoundError(f"No job.json in {job_dir}")
    return spec


def write_state(job_dir: str, state: dict) -> None:
    _write_json(os.path.join(job_dir, "state.json"), {**state, "updated_at": time.time()})


def read_state(job_dir: str) -> dict | None:
    state = _read_json(os.path.join(job_dir, "state.json"))
    if state and state.get("phase") not in TERMINAL and _looks_dead(state):
        state = {**state, "phase": "error", "error": "Worker stopped unexpectedly"}
    return state


def _looks_dead(state: dict) -> bool:
    if state.get("phase") == "queued":
        return time.time() - state.get("created_at", 0) > STALE_AFTER
    pid = state.get("pid")
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return False
    except ProcessLookupError:
        return time.time() - state.get("updated_at", 0) > 2
    except PermissionError:
        return False


def request_cancel(job_dir: str) -> None:
    open(os.path.join(job_dir, "cancel"), "w").close()


def cancel_requested(job_dir: str) -> bool:
    return os.path.exists(os.path.join(job_dir, "cancel"))


def list_jobs(jobs_root: str) -> list[dict]:
    if not os.path.isdir(jobs_root):
        return []
    out = []
    for name in sorted(os.listdir(jobs_root)):
        st = read_state(os.path.join(jobs_root, name))
        if st:
            out.append(st)
    return out


def remove_job(jobs_root: str, job_id: str) -> None:
    path = os.path.join(jobs_root, os.path.basename(job_id))
    shutil.rmtree(path, ignore_errors=True)


# ---- launching -------------------------------------------------------------


def clean_env() -> dict:
    """Env for system binaries: drop what Decky's PyInstaller runtime injects."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("LD_LIBRARY_PATH", "LD_PRELOAD", "PYTHONHOME", "PYTHONPATH", "SSL_CERT_FILE")}
    if "LD_LIBRARY_PATH_ORIG" in os.environ:
        env["LD_LIBRARY_PATH"] = os.environ["LD_LIBRARY_PATH_ORIG"]
    uid = os.getuid()
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{uid}/bus")
    return env


def launch_worker(job_dir: str, py_modules_dir: str, python: str = SYSTEM_PYTHON) -> dict:
    """Start the worker detached from the caller. Returns how it was launched."""
    job_id = os.path.basename(job_dir.rstrip("/"))
    unit = f"gameyfin-install-{job_id}"
    env = clean_env()
    cmd = [python, "-m", "gameyfin.worker", job_dir]
    try:
        subprocess.run(
            ["systemd-run", "--user", "--quiet", "--collect", f"--unit={unit}",
             f"--setenv=PYTHONPATH={py_modules_dir}", "--setenv=PYTHONDONTWRITEBYTECODE=1",
             "--property=Nice=5", "--property=IOSchedulingClass=idle", *cmd],
            env=env, check=True, capture_output=True, timeout=15,
        )
        return {"method": "systemd-run", "unit": unit}
    except (OSError, subprocess.SubprocessError):
        # Fallback: detached session. Survives plugin reloads (KillMode=process).
        env.update(PYTHONPATH=py_modules_dir, PYTHONDONTWRITEBYTECODE="1")
        log = open(os.path.join(job_dir, "worker.log"), "ab")
        proc = subprocess.Popen(cmd, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                start_new_session=True, close_fds=True)
        log.close()
        return {"method": "popen", "pid": proc.pid}
