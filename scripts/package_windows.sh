#!/bin/bash
# Build the Windows zip from the verified payload tree.
#
# The payload already carries the Windows engine (vendor/win) and the portable
# Python sources that stand in for the compiled modules. The only Windows
# specific step is materializing the npm workspace links: Windows archive
# tools do not reliably restore symlinks, so the zip stores real directories.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
SRC="$ROOT/dist/deb/greymicroagent/opt/greymicroagent"
OUT="$ROOT/dist/win"

if [ ! -d "$SRC" ]; then
    echo "package_windows: run scripts/package_deb.sh first (no staged tree)" >&2
    exit 1
fi

DEB=$(ls "$ROOT"/dist/deb/*.deb | head -1)
VERSION=$(basename "$DEB" | sed 's/^greymicroagent_\(.*\)_amd64\.deb$/\1/')
ZIP="$OUT/greymicroagent_${VERSION}_windows-x86_64.zip"

rm -rf "$OUT/tree"
mkdir -p "$OUT/tree"
rsync -aL --exclude '__pycache__' "$SRC/" "$OUT/tree/"
find "$OUT/tree" -xtype l -delete
rm -f "$ZIP"
(cd "$OUT/tree" && zip -qr "$ZIP" .)
rm -rf "$OUT/tree"

echo "windows zip: $ZIP"
ls -la "$ZIP"
