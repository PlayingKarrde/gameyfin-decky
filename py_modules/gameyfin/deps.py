"""Bundled dependency installers (VC++, DirectX, XNA, OpenAL) run once per Proton prefix.

Many Windows games ship their redistributables in the game folder (GOG's ``__redist``,
``_CommonRedist`` and similar) and expect an installer to have run them. Proton covers
much of this with Wine's own DLLs, but some games still need the real VC++ runtime.

The prefix doesn't exist until Steam first launches the shortcut, and only Steam knows
which Proton build and library folder it uses. So instead of running anything at install
time, the shortcut's launch options become::

    /bin/bash "<game>/.gameyfin-deps/run.sh" %command%

On launch, ``run.sh`` finds Proton in Steam's command line, runs each listed installer
silently in the game's own prefix (skipping ones already done there), then starts the
game. ``/bin/bash`` in front means the script needs no exec bit (exFAT SD cards).
Deleting the prefix makes them run again on the next launch.

Silent flags are the documented ones for each installer; none of this has been tried on a
Deck yet, which is why failures are logged and never block the game from starting.
"""

from __future__ import annotations

import os
import re

DIR = ".gameyfin-deps"
SCRIPT = "run.sh"
LIST = "list.tsv"
MAX_DEPTH = 5

_VC = re.compile(r"^vc_?redist.*\.exe$", re.IGNORECASE)
_YEAR = re.compile(r"(?<!\d)(2005|2008|2010|2012|2013|2015|2017|2019|2022)(?!\d)")

# Characters we won't put inside Steam's launch-option string (it is shell-parsed).
_UNSAFE_PATH = re.compile(r'["$`\\]')

WRAPPER = r'''#!/bin/bash
# Gameyfin for Decky: run this game's bundled redistributables (VC++, DirectX, ...) once
# per Proton prefix, then start the game. Steam runs this as: /bin/bash run.sh %command%
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
game="$(dirname "$here")"
prefix="${STEAM_COMPAT_DATA_PATH:-}"

# Steam's command: [reaper ... --] [steam-launch-wrapper --] [runtime entry point ... --] <proton> <verb> <exe> ...
# Re-use it from the runtime entry point (or Proton itself) up to Proton, minus Steam's
# own wrappers, so the installers run in the same container, Proton build and prefix.
start=-1; proton=-1; i=0
for a in "$@"; do
  case "$a" in
    *_v2-entry-point|*/entry-point) [ $start -lt 0 ] && start=$i ;;
    */proton) proton=$i; break ;;
  esac
  i=$((i + 1))
done

if [ -n "$prefix" ] && [ $proton -ge 0 ] && [ -f "$here/list.tsv" ]; then
  [ $start -lt 0 ] && start=$proton
  args=("$@")
  cmd=("${args[@]:$start:$((proton - start + 1))}")
  mkdir -p "$prefix"
  done_file="$prefix/gameyfin-deps.done"
  log="$prefix/gameyfin-deps.log"
  touch "$done_file"
  while IFS=$'\t' read -r key kind rel flags; do
    [ -z "$key" ] && continue
    grep -qxF "$key" "$done_file" && continue
    file="$game/$rel"
    [ -f "$file" ] || continue
    echo "[$(date '+%F %T')] $kind $rel $flags" >>"$log"
    # shellcheck disable=SC2086  # flags are a fixed list of switches from list.tsv
    if [ "$kind" = msi ]; then
      win="Z:${file//\//\\}"
      ( cd "$(dirname "$file")" && "${cmd[@]}" waitforexitandrun msiexec /i "$win" $flags ) >>"$log" 2>&1
    else
      ( cd "$(dirname "$file")" && "${cmd[@]}" waitforexitandrun "$file" $flags ) >>"$log" 2>&1
    fi
    echo "  exit $?" >>"$log"
    echo "$key" >>"$done_file"  # attempted: don't retry a failing installer on every launch
  done <"$here/list.tsv"
fi

exec "$@"
'''


def _vc_flags(rel: str) -> str:
    years = _YEAR.findall(rel)
    if years and years[-1] in ("2005", "2008"):
        return "/q"  # IExpress-wrapped MSI: no /norestart
    return "/q /norestart"  # 2010's own setup and the WiX Burn bundles (2012+) take both


def classify(name: str, rel: str) -> tuple[int, str, str, str] | None:
    """(order, label, kind, flags) for a known redistributable installer, else None.
    VC++ goes first: other installers may need it."""
    low = name.lower()
    if _VC.match(low):
        years = _YEAR.findall(rel)
        arch = "x64" if re.search(r"x64|amd64", low) else "x86" if "x86" in low else ""
        label = " ".join(p for p in ("Visual C++", years[-1] if years else "", arch) if p)
        return 0, label, "exe", _vc_flags(rel)
    if low == "dxsetup.exe":
        return 1, "DirectX", "exe", "/silent"
    if re.match(r"^xnafx\d+_redist\.msi$", low):
        return 2, "XNA Framework", "msi", "/qn"
    if low == "oalinst.exe":
        return 2, "OpenAL", "exe", "/s"
    return None


def find_redists(install_dir: str) -> list[dict]:
    """Known redistributable installers in the game folder: [{key, label, kind, rel, flags}].

    Duplicates (the same file in two folders) are listed once.
    """
    found, seen = [], set()
    root_depth = install_dir.rstrip("/").count("/")
    for dirpath, dirnames, filenames in os.walk(install_dir):
        depth = dirpath.rstrip("/").count("/") - root_depth
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and depth < MAX_DEPTH)
        for fn in sorted(filenames):
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, install_dir)
            hit = classify(fn, rel)
            if not hit or "\t" in rel or "\n" in rel:
                continue
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            dedupe = (fn.lower(), size)
            if dedupe in seen:
                continue
            seen.add(dedupe)
            rank, label, kind, flags = hit
            found.append((rank, rel, {"key": rel, "label": label, "kind": kind, "rel": rel, "flags": flags}))
    return [r for _, _, r in sorted(found, key=lambda x: (x[0], x[1]))]


def write_wrapper(install_dir: str, redists: list[dict]) -> str | None:
    """Write .gameyfin-deps/{run.sh,list.tsv}; returns the wrapper's path relative to
    install_dir, or None (nothing to run, or a path Steam's launch options can't hold)."""
    d = os.path.join(install_dir, DIR)
    if not redists or _UNSAFE_PATH.search(install_dir):
        return None
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, SCRIPT), "w", encoding="utf-8", newline="\n") as f:
        f.write(WRAPPER)
    with open(os.path.join(d, LIST), "w", encoding="utf-8", newline="\n") as f:
        for r in redists:
            f.write(f"{r['key']}\t{r['kind']}\t{r['rel']}\t{r['flags']}\n")
    try:
        os.chmod(os.path.join(d, SCRIPT), 0o755)
    except OSError:
        pass  # run through /bin/bash anyway
    return f"{DIR}/{SCRIPT}"

