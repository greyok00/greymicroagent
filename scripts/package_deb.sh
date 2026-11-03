#!/bin/bash
# package_deb.sh — build the greymini .deb (self-contained portable fork).
# dpkg layout: /opt/greymini = the frozen tree (launcher, compiled modules,
# tui dist, vendored runtime); /usr/local/bin/greymini = symlink.
# The deb's postinst runs bin/verify_compiled.py so a broken install fails
# loudly at dpkg time, never silently at first boot.
# Local-only artifact; never uploaded to a repo (owner directive).
set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
OUT="$ROOT/dist/deb"
PKGROOT="$OUT/greymini"
VERSION="$(python3 "$ROOT/bin/version.sh" 2>/dev/null || true)"
[ -n "$VERSION" ] || VERSION="$(node "$ROOT/tui/packages/coding-agent/dist/cli.js" --version 2>/dev/null | tail -1 | tr -dc '0-9.')"
[ -n "$VERSION" ] || VERSION="0.7.5.1"

echo "== packaging greymini $VERSION =="
rm -rf "$OUT"
mkdir -p "$PKGROOT/DEBIAN" "$PKGROOT/opt/greymini" "$PKGROOT/usr/local/bin"
cat > "$PKGROOT/DEBIAN/control" <<EOF
Package: greymini
Version: $VERSION
Section: utils
Priority: optional
Architecture: amd64
Depends: python3 (>= 3.13), nodejs (>= 22), libc6, libstdc++6, libgcc-s1, libnvidia-ml1 | libcuda1
Maintainer: grey <local>
Description: greymini — portable minimized offline fork (2B hybrid)
 Fully Cython-compiled agent core/tools/services; renamed private
 llama-server (greymini-server) with session slots from :7080 (model) and
 :7081 (slimtoken lane); Node TUI under the @greyagent scope (its compiled scope); frozen,
 hash-pinned artifacts (state/MANIFEST.json) and an on-demand, masked
 lifecycle. Port policy in ~/.greymini/agent/port_policy.json.
EOF
# payload: everything, minus transient scratch
tar -C "$ROOT" \
    --exclude='__pycache__' --exclude='.pytest_cache' \
    --exclude='dist/deb' \
    --exclude='*/dist/*.map' \
    --exclude='build/src/build' \
    --exclude='state/model-server.log' \
    -cf - bin core tools services build mcp scripts tests tui vendor pytest.ini config \
        state/MANIFEST.json \
| tar -xf - -C "$PKGROOT/opt/greymini"
ln -sf /opt/greymini/bin/greymini "$PKGROOT/usr/local/bin/greymini"
cat > "$PKGROOT/DEBIAN/postinst" <<'EOF'
#!/bin/bash
set -e
if ! python3 /opt/greymini/bin/verify_compiled.py; then
  echo "greymini: frozen-tree verification FAILED after install" >&2
  exit 1
fi
echo "greymini: frozen tree verified. ~/.greymini/agent seeds on first launch."
EOF
chmod 755 "$PKGROOT/DEBIAN/postinst"
du -sh "$PKGROOT/opt/greymini" | sed 's/^/payload: /'
dpkg-deb --build "$PKGROOT" "$OUT/greymini_${VERSION}_amd64.deb"
ls -la "$OUT" | grep deb