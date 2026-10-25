#!/bin/bash
# package_appimage.sh — bundle the frozen greyagent into a single AppImage.
# Uses linuxdeploy + linuxdeploy-plugin-python (fetched from GitHub releases;
# cached in scripts/.linuxdeploy). The payload = the same frozen tree as the
# deb: compiled .so modules, @greyagent/dist TUI, vendored llama/ggml libs,
# vendor/chromium, config symlink. The bundled llama binary is renamed
# greyagent-server + rpath-$ORIGIN patched, port :6666, lane :6667.
# Output: dist/AppImage/greyagent-x86_64.AppImage
# NOTE (2026-10-24): script is written + not yet executed here — the deb is
# this build's exercised artifact; AppImage run needs the linuxdeploy apps
# (network fetch) and ~2 GB of bundling; run it when shipping is wanted.
set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
OUT="$ROOT/dist/AppImage"
CACHE="$ROOT/scripts/.linuxdeploy"
VERSION="$(node "$ROOT/tui/packages/coding-agent/dist/cli.js" --version 2>/dev/null | tail -1 | tr -dc '0-9.')"
APPDIR="$OUT/greyagent.AppDir"

echo "== bundling greyagent $VERSION -> AppImage =="
mkdir -p "$APPDIR" "$CACHE"
# 1) fetch linuxdeploy once
[ -f "$CACHE/linuxdeploy" ] || {
  echo "fetching linuxdeploy + python plugin (once)..."
  curl -sL https://github.com/linuxdeploy/linuxdeploy/releases/latest/download/linuxdeploy-x86_64.AppImage -o "$CACHE/linuxdeploy"
  curl -sL https://github.com/linuxdeploy/linuxdeploy-plugin-python/releases/latest/download/linuxdeploy-plugin-python-x86_64.AppImage -o "$CACHE/linuxdeploy-plugin-python"
  chmod +x "$CACHE"/linuxdeploy*
}
# 2) AppDir layout
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -a "$ROOT/bin/greyagent" "$APPDIR/usr/bin/greyagent"
[ -f "$ROOT/docs/greyagent-logo.png" ] && cp "$ROOT/docs/greyagent-logo.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/greyagent.png" || true
cat > "$APPDIR/usr/share/applications/greyagent.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=greyagent
Comment=Hardened offline agent (own model :6666, lane :6667, compiled core)
Exec=greyagent
Icon=greyagent
Terminal=true
Categories=Development;
EOF
# 3) payload + wrapper so the AppDir's internal paths stay relative
mkdir -p "$APPDIR/opt"
cp -a "$ROOT/." "$APPDIR/opt/greyagent/"
cat > "$APPDIR/usr/bin/greyagent" <<'EOF'
#!/bin/bash
DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../opt/greyagent" && pwd)"
exec "$DIR/bin/greyagent" "$@"
EOF
chmod +x "$APPDIR/usr/bin/greyagent"
# 4) run linuxdeploy
ARCH=x86_64 LD_LIBRARY_PATH= "$CACHE/linuxdeploy" \
  --appdir "$APPDIR" --output appimage --icon-file "$APPDIR/usr/share/icons/hicolor/256x256/apps/greyagent.png" 2>&1 | tail -4
ls -la "$OUT" | grep AppImage || echo "AppImage step: check linuxdeploy output above"