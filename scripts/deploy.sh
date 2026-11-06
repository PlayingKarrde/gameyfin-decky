#!/usr/bin/env bash
# Build the plugin and push it to the Deck, then restart Decky.
#   DECK_HOST   ssh alias/host (default: deck)
#   NO_BUILD=1  skip the frontend build
#   NO_RESTART=1 skip restarting plugin_loader
set -euo pipefail
cd "$(dirname "$0")/.."

HOST="${DECK_HOST:-deck}"
NAME="gameyfin-decky"
REMOTE_DIR="homebrew/plugins/$NAME"   # relative to the deck user's $HOME

# Stage exactly what Decky loads (same layout as the release zip).
NO_BUILD="${NO_BUILD:-}" scripts/package.sh >/dev/null
STAGE="out/$NAME"

# Decky re-chowns the plugin dir to root on every start, so we can't rsync into it
# directly. Sync to a deck-owned staging dir, then do one root rsync whose exact
# arguments are whitelisted in /etc/sudoers.d/zz-decky-dev on the Deck:
#   deck ALL=(root) NOPASSWD: /usr/bin/rsync -a --delete /home/deck/.cache/gameyfin-decky-stage/ /home/deck/homebrew/plugins/gameyfin-decky/
#   deck ALL=(root) NOPASSWD: /usr/bin/systemctl restart plugin_loader
REMOTE_STAGE=".cache/$NAME-stage"
rsync -az --delete --mkpath "$STAGE/" "$HOST:$REMOTE_STAGE/"
ssh "$HOST" sudo -n /usr/bin/rsync -a --delete "/home/deck/$REMOTE_STAGE/" "/home/deck/$REMOTE_DIR/"
echo "Synced to $HOST:~/$REMOTE_DIR"

if [[ "${NO_RESTART:-}" != 1 ]]; then
  ssh "$HOST" sudo -n systemctl restart plugin_loader
  echo "Restarted plugin_loader"
fi
