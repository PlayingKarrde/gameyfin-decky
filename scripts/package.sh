#!/usr/bin/env bash
# Assemble exactly what Decky loads into out/gameyfin-decky/ and zip it.
#   NO_BUILD=1  skip the frontend build
# Output: out/gameyfin-decky-<version>.zip (top-level folder: gameyfin-decky/)
set -euo pipefail
cd "$(dirname "$0")/.."

NAME="gameyfin-decky"
VERSION="$(python3 -c 'import json; print(json.load(open("package.json"))["version"])')"

[[ "${NO_BUILD:-}" == 1 ]] || pnpm build

STAGE="out/$NAME"
rm -rf "$STAGE" && mkdir -p "$STAGE/dist"
cp plugin.json package.json main.py LICENSE README.md "$STAGE/"
cp dist/index.js "$STAGE/dist/"
cp -r py_modules "$STAGE/"
find "$STAGE" -name '__pycache__' -prune -exec rm -rf {} +

ZIP="out/$NAME-$VERSION.zip"
rm -f "$ZIP"
python3 - "$STAGE" "$ZIP" <<'PY'
import os, sys, zipfile
stage, out = sys.argv[1], sys.argv[2]
root = os.path.dirname(stage)
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for d, _, files in os.walk(stage):
        for f in sorted(files):
            p = os.path.join(d, f)
            z.write(p, os.path.relpath(p, root))
PY
echo "$ZIP"
