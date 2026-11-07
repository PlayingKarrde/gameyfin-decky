#!/usr/bin/env bash
# Refresh the committed copies of decky-common (py_modules/gameyfin/common, src/common, scripts/cdp.py).
#   DECKY_COMMON=path   checkout to copy from (default: ../decky-common)
#   --check             CI: fail if the copies differ from the commit recorded in .decky-common
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "${1:-}" == --check ]]; then
  rev="$(cat .decky-common)"
  [[ "$rev" =~ ^[0-9a-f]{40}$ ]] || { echo ".decky-common is '$rev', not a commit: sync from a committed decky-common" >&2; exit 1; }
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  git clone -q https://github.com/PlayingKarrde/decky-common "$tmp"
  git -C "$tmp" checkout -q "$rev"
  "$tmp/sync.sh" . gameyfin >/dev/null
  paths=(.decky-common py_modules/gameyfin/common src/common scripts/cdp.py)
  # Working tree vs what's checked in (index), plus files the sync adds that aren't checked in.
  if ! git diff --quiet -- "${paths[@]}" || [[ -n "$(git ls-files --others --exclude-standard -- "${paths[@]}")" ]]; then
    git status --short -- "${paths[@]}" >&2
    echo "decky-common copies differ from $rev: edit decky-common and re-sync, don't edit the copies" >&2
    exit 1
  fi
  echo "decky-common copies match $rev"
else
  "${DECKY_COMMON:-../decky-common}/sync.sh" . gameyfin
fi
