#!/bin/bash
# package_deb.sh — build the greylocalrag .deb (self-contained portable fork).
# dpkg layout: /opt/greylocalrag = the frozen tree (launcher, compiled modules,
# tui dist, vendored runtime); /usr/local/bin/greylocalrag = symlink.
# The deb's postinst runs bin/verify_compiled.py so a broken install fails
# loudly at dpkg time, never silently at first boot.
# Local-only artifact; never uploaded to a repo (owner directive).
set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
OUT="$ROOT/dist/deb"
PKGROOT="$OUT/greylocalrag"
VERSION="$(python3 "$ROOT/bin/version.sh" 2>/dev/null || true)"
[ -n "$VERSION" ] || VERSION="$(node "$ROOT/tui/packages/coding-agent/dist/cli.js" --version 2>/dev/null | tail -1 | tr -dc '0-9.')"
[ -n "$VERSION" ] || VERSION="0.7.5.1"

echo "== packaging greylocalrag $VERSION =="
rm -rf "$OUT"
mkdir -p "$PKGROOT/DEBIAN" "$PKGROOT/opt/greylocalrag" "$PKGROOT/usr/local/bin"
cat > "$PKGROOT/DEBIAN/control" <<EOF
Package: greylocalrag
Version: $VERSION
Section: utils
Priority: optional
Architecture: amd64
Depends: python3 (>= 3.13), nodejs (>= 22), libc6, libstdc++6, libgcc-s1, libnvidia-ml1 | libcuda1
Maintainer: grey <local>
Description: greylocalrag — portable minimized offline fork (2B hybrid)
 Fully Cython-compiled agent core/tools/services; fork-unique private
 llama-server (greylocalrag-server) with session slots inside the fork-owned
 7640-7647 port block (:7640 model, :7641 slimtoken lane); Node TUI under the @greyagent scope (its compiled scope); frozen,
 hash-pinned artifacts (state/MANIFEST.json) and an on-demand, masked
 lifecycle. Port policy in ~/.greylocalrag/agent/port_policy.json.
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
| tar -xf - -C "$PKGROOT/opt/greylocalrag"
ln -sf /opt/greylocalrag/bin/greylocalrag "$PKGROOT/usr/local/bin/greylocalrag"
cat > "$PKGROOT/DEBIAN/postinst" <<'EOF'
#!/bin/bash
set -e
if ! python3 /opt/greylocalrag/bin/verify_compiled.py; then
  echo "greylocalrag: frozen-tree verification FAILED after install" >&2
  exit 1
fi
echo "greylocalrag: frozen tree verified. ~/.greylocalrag/agent seeds on first launch."
EOF
chmod 755 "$PKGROOT/DEBIAN/postinst"
du -sh "$PKGROOT/opt/greylocalrag" | sed 's/^/payload: /'
dpkg-deb --build "$PKGROOT" "$OUT/greylocalrag_${VERSION}_amd64.deb"
ls -la "$OUT" | grep deb