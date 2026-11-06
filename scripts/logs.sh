#!/usr/bin/env bash
# Tail plugin logs from the Deck.  Usage: scripts/logs.sh [lines] [-f]
#   -f / --loader : follow, or show the plugin_loader journal instead
set -euo pipefail
HOST="${DECK_HOST:-deck}"
N="${1:-200}"
case "${2:-}" in
  -f)        ssh -t "$HOST" "tail -n $N -F ~/homebrew/logs/gameyfin-decky/*" ;;
  --loader)  ssh "$HOST" "journalctl -u plugin_loader -n $N --no-pager" ;;
  *)         ssh "$HOST" "tail -n $N ~/homebrew/logs/gameyfin-decky/*" ;;
esac
