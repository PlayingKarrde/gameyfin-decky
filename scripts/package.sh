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

# Bundled innoextract (zlib licence) for GOG-style installers. Pinned by checksum.
INNO_VER="1.9"
INNO_SHA256="008efe5011476ccc4aae17c3e22038b5a1bc5c7aad2b9d4d869537bf3874d21f"
INNO_TAR="vendor/innoextract-$INNO_VER-linux.tar.xz"
mkdir -p vendor
if ! echo "$INNO_SHA256  $INNO_TAR" | sha256sum -c --status - 2>/dev/null; then
  curl -sfL -o "$INNO_TAR" "https://github.com/dscharrer/innoextract/releases/download/$INNO_VER/innoextract-$INNO_VER-linux.tar.xz"
  echo "$INNO_SHA256  $INNO_TAR" | sha256sum -c --quiet -
fi
mkdir -p "$STAGE/bin" "$STAGE/licenses"
tar -xJf "$INNO_TAR" -O "innoextract-$INNO_VER-linux/bin/amd64/innoextract" > "$STAGE/bin/innoextract"
tar -xJf "$INNO_TAR" -O "innoextract-$INNO_VER-linux/license/innoextract.LICENSE" > "$STAGE/licenses/innoextract.LICENSE"
chmod 755 "$STAGE/bin/innoextract"
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
