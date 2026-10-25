#!/bin/bash
# package_deb.sh — build the greyagent .deb (self-contained hardened fork).
# dpkg layout: /opt/greyagent = the frozen tree (launcher, compiled modules,
# tui dist, vendored runtime); /usr/local/bin/greyagent = symlink.
# The deb's postinst runs bin/verify_compiled.py so a broken install fails
# loudly at dpkg time, never silently at first boot.
# Local-only artifact; never uploaded to a repo (owner directive).
set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
OUT="$ROOT/dist/deb"
PKGROOT="$OUT/greyagent"
VERSION="$(python3 "$ROOT/bin/version.sh" 2>/dev/null || true)"
[ -n "$VERSION" ] || VERSION="$(node "$ROOT/tui/packages/coding-agent/dist/cli.js" --version 2>/dev/null | tail -1 | tr -dc '0-9.')"
[ -n "$VERSION" ] || VERSION="0.7.5.1"

echo "== packaging greyagent $VERSION =="
rm -rf "$OUT"
mkdir -p "$PKGROOT/DEBIAN" "$PKGROOT/opt/greyagent" "$PKGROOT/usr/local/bin"
cat > "$PKGROOT/DEBIAN/control" <<EOF
Package: greyagent
Version: $VERSION
Section: utils
Priority: optional
Architecture: amd64
Depends: python3 (>= 3.13), nodejs (>= 22), libc6, libstdc++6, libgcc-s1, libnvidia-ml1 | libcuda1
Maintainer: grey <local>
Description: greyagent — hardened offline fork of the cortex agent family
 Fully Cython-compiled agent core/tools/services; renamed private
 llama-server (greyagent-server) on port 6666 with its slimtoken lane on
 6667; Node TUI under the @greyagent scope; frozen, hash-pinned artifacts
 (state/MANIFEST.json) and an on-demand, masked lifecycle. Port policy in
 ~/.greyagent/agent/port_policy.json (:11600 untouched, :11434 dead).
EOF
# payload: everything, minus transient scratch
tar -C "$ROOT" \
    --exclude='__pycache__' --exclude='.pytest_cache' \
    --exclude='dist/deb' \
    --exclude='*/dist/*.map' \
    --exclude='build/src/build' \
    --exclude='state/model-server.log' \
    -cf - bin core tools services build mcp scripts tests tui vendor pytest.ini config \
    | tar -xf - -C "$PKGROOT/opt/greyagent"
ln -sf /opt/greyagent/bin/greyagent "$PKGROOT/usr/local/bin/greyagent"
cat > "$PKGROOT/DEBIAN/postinst" <<'EOF'
#!/bin/bash
set -e
if ! python3 /opt/greyagent/bin/verify_compiled.py; then
  echo "greyagent: frozen-tree verification FAILED after install" >&2
  exit 1
fi
echo "greyagent: frozen tree verified. ~/.greyagent/agent seeds on first launch."
EOF
chmod 755 "$PKGROOT/DEBIAN/postinst"
du -sh "$PKGROOT/opt/greyagent" | sed 's/^/payload: /'
dpkg-deb --build "$PKGROOT" "$OUT/greyagent_${VERSION}_amd64.deb"
ls -la "$OUT" | grep deb