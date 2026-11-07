#!/usr/bin/env python3
"""Dev CLI for the Gameyfin client, using credentials from ./.env.

  scripts/gf.py test
  scripts/gf.py list [query] [--page N] [--size N]
  scripts/gf.py game <id>
  scripts/gf.py providers
  scripts/gf.py install <id> --dest DIR [--jobs DIR] [--cancel-after SECONDS]
  scripts/gf.py art <id>         # Steam artwork plan (SteamGridDB too, if a key is set)

.env keys (CRLF tolerated): serverurl / GAMEYFIN_URL, api / GAMEYFIN_TOKEN, optional sgdb / SGDB_KEY
"""

import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "py_modules"))

from gameyfin.client import GameyfinClient, GameyfinError  # noqa: E402
from gameyfin import jobs, sgdb  # noqa: E402
from gameyfin.library import game_detail, page_summary  # noqa: E402


def load_env(path: str) -> dict:
    env = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return env


def env_all() -> dict:
    return {**load_env(os.path.join(ROOT, ".env")), **os.environ}


def make_client() -> GameyfinClient:
    env = env_all()
    url = env.get("GAMEYFIN_URL") or env.get("serverurl")
    token = env.get("GAMEYFIN_TOKEN") or env.get("api")
    if not url or not token:
        sys.exit("Set serverurl/api (or GAMEYFIN_URL/GAMEYFIN_TOKEN) in .env")
    return GameyfinClient(url, token)


def fmt(n) -> str:
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{u}"
        n /= 1024
    return f"{n:.1f}TB"


def cmd_install(c: GameyfinClient, game_id: str, dest: str, jobs_root: str, cancel_after: float | None) -> int:
    """Run the real worker as a subprocess and render its state.json, like the UI will."""
    game = c.get_game(game_id)
    jd = jobs.create_job(jobs_root, {"game_id": game_id, "title": game.get("title"), "dest_root": dest,
                                     "server_url": c.base_url, "file_size": game.get("fileSize")})
    env = {**os.environ, "GAMEYFIN_TOKEN": c.token, "PYTHONPATH": os.path.join(ROOT, "py_modules")}
    proc = subprocess.Popen([sys.executable, "-m", "gameyfin.worker", jd], env=env)
    t0 = time.time()
    while proc.poll() is None:
        time.sleep(0.5)
        st = jobs.read_state(jd) or {}
        pct = f"{100 * st['done'] / st['total']:.0f}%" if st.get("total") else "?"
        print(f"\r{st.get('phase', '?'):12} {fmt(st.get('done'))} / {fmt(st.get('total'))} {pct:>4}"
              f"  {fmt(st.get('speed'))}/s   ", end="", flush=True)
        if cancel_after and time.time() - t0 > cancel_after and not jobs.cancel_requested(jd):
            print("\n-> requesting cancel")
            jobs.request_cancel(jd)
    st = jobs.read_state(jd) or {}
    print(f"\nexit={proc.returncode} {json.dumps({k: st.get(k) for k in ('phase', 'error', 'install_dir')})}"
          f" in {time.time() - t0:.1f}s")
    return proc.returncode


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("test")
    p = sub.add_parser("list")
    p.add_argument("query", nargs="?", default="")
    p.add_argument("--page", type=int, default=0)
    p.add_argument("--size", type=int, default=20)
    g = sub.add_parser("game")
    g.add_argument("id")
    sub.add_parser("providers")
    a = sub.add_parser("art")
    a.add_argument("id")
    i = sub.add_parser("install")
    i.add_argument("id")
    i.add_argument("--dest", required=True)
    i.add_argument("--jobs", default=None)
    i.add_argument("--cancel-after", type=float, default=None)
    args = ap.parse_args()

    c = make_client()
    try:
        if args.cmd == "test":
            out = c.test_connection()
        elif args.cmd == "list":
            out = page_summary(c.list_games(page=args.page, size=args.size, q=args.query or None))
        elif args.cmd == "install":
            jobs_root = args.jobs or os.path.join(args.dest, ".jobs")
            sys.exit(cmd_install(c, args.id, args.dest, jobs_root, args.cancel_after))
        elif args.cmd == "art":
            game = c.get_game(args.id)
            env = env_all()
            key = env.get("SGDB_KEY") or env.get("sgdb")
            sg = sgdb.SgdbClient(key) if key else None
            sgdb_id = sgdb.resolve(sg, game) if sg else None
            assets = sg.assets(sgdb_id) if sgdb_id else {}
            out = {"title": game.get("title"), "sgdb_key": bool(key), "sgdb_id": sgdb_id,
                   "plan": sgdb.art_plan(game, assets)}
        elif args.cmd == "game":
            out = game_detail(c.get_game(args.id))
        else:
            out = c.download_providers()
    except GameyfinError as e:
        sys.exit(f"error: {e} (status={e.status}, code={e.code})")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
