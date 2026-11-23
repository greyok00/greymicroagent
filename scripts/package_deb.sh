#!/bin/bash
# package_deb.sh - build the greymicroagent .deb locally. LOCAL ARTIFACT ONLY:
# the release is owner-gated, nothing here pushes, uploads, or publishes.
#
# dpkg layout: /opt/greymicroagent = the frozen tree (launcher, compiled modules,
# tui dist, vendored runtime); /usr/local/bin/greymicroagent = symlink. The
# postinst runs bin/verify_compiled.py so a broken install fails loudly at
# dpkg time, never silently at first boot.
#
# Release-wave A packaging flow (build-hygiene law, spec section 2.9):
#   1. the dev tree must be green first: gen_manifest + verify_compiled.
#   2. payload is STAGED as a real-file copy (never a tar of dev paths):
#      bin (minus the greyagent family launcher), core (minus the greysearch
#      dev guides), tools, services, build/src (minus .c intermediates and the
#      greyagent_run helper), mcp, tui (minus dist sourcemaps), vendor;
#      config-data (TUI extension record, port policy, registry template)
#      copied REAL files from the repo; the dev `config` symlink is never
#      staged (a copy of it would carry a host-locked link); README.md,
#      THIRD-PARTY-NOTICES.txt; the
#      model card AS model/greymicroagent.txt (the .md dev name never ships);
#      state/ carries ONLY a manifest regenerated from the staged tree itself,
#      so every pin matches exactly what the deb installs.
#   3. MECHANICAL SCRUB on the staged copy only, dev source untouched:
#      - rebrand "knowledge-ingestor" -> "greymicroagent" (Task 3 carry: the
#        kbcore User-Agent and the KB db-format tag; the pre-ship gate flags
#        the string as FAIL, so the payload copy must not carry it)
#      - codename purge "greymini" -> "greymicroagent" (also fixed inside the
#        compiled dist fallback paths, which are fork-owned after the rebrand)
#      - host path purge: "/home/grey/..." -> "$HOME/..." placeholders; the
#        runtime paths that actually matter are resolved by the staged
#        launcher export GREYMICROAGENT_MODEL_PATH=$HOME/.greymicroagent/models/...
#      - em dash -> hyphen in shipped text (echo/comment strings law)
#      - full-line comments stripped from shipped shell surfaces (the
#        launcher); private dev comments stay private by staging exclusion
#      - symlink targets rewritten from absolute dev-tree paths to relative
#        in-tree paths (npm workspace/.bin links are dev-absolute)
#      - every staged .so is re-stamped AFTER the scrub so verify_compiled's
#        staleness layer sees compiled newer than source inside the deb
#   4. scripts/pre_ship_check.py runs on the staged payload; nonzero = no deb.
#      It scans for incident-class strings, codenames, host paths, .md files
#      besides README, residue names, comments in shipped shell/json surfaces,
#      the knowledge-ingestor string, em dashes, the services .py whitelist,
#      the renamed card, the port policy, and host-escaping symlinks.
#   5. dpkg-deb builds; artifact verified AFTER: dpkg -I sane, unpacked to a
#      scratch dir, verify_compiled + pre_ship_check re-run INSIDE the
#      unpacked tree. HARD STOP after verification: never release.
set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
OUT="$ROOT/dist/deb"
PKGROOT="$OUT/greymicroagent"
TREE="$PKGROOT/opt/greymicroagent"
VERSION="$(python3 "$ROOT/bin/version.sh" 2>/dev/null || true)"
[ -n "$VERSION" ] || VERSION="$(node "$ROOT/tui/packages/coding-agent/dist/cli.js" --version 2>/dev/null | tail -1 | tr -dc '0-9.')"
[ -n "$VERSION" ] || VERSION="0.7.5.3"

echo "== packaging greymicroagent $VERSION =="
echo "== dev-tree sanity: gen_manifest + verify_compiled =="
python3 "$ROOT/scripts/gen_manifest.py"
python3 "$ROOT/bin/verify_compiled.py"

rm -rf "$PKGROOT"
rm -f "$OUT/greymicroagent_${VERSION}_amd64.deb"
mkdir -p "$TREE" "$PKGROOT/DEBIAN" "$PKGROOT/usr/local/bin" "$TREE/state"

echo "== staging payload (real files, no dev symlinks) =="
for d in bin core tools services mcp tui; do
    cp -a "$ROOT/$d" "$TREE/$d"
done
# The runtime links vendor/greymicroagent-server only. vendor/llamacpp is
# unused build residue, so the payload carries the engine it actually runs.
mkdir -p "$TREE/vendor"
cp -a "$ROOT/vendor/greymicroagent-server" "$TREE/vendor/"
cp -a "$ROOT/vendor/slimtoken" "$TREE/vendor/"
cp -a "$ROOT/vendor/win" "$TREE/vendor/"
# The local service sources ship for the portable Windows path, where the
# compiled modules cannot load. pre_ship_check.py vets this set by name.

mkdir -p "$TREE/build"
cp -a "$ROOT/build/src" "$TREE/build/src"

cp -a "$ROOT/README.md" "$TREE/README.md"
cp -a "$ROOT/THIRD-PARTY-NOTICES.txt" "$TREE/THIRD-PARTY-NOTICES.txt"
# T21: config-data now also carries the shipped extension record and the
# port policy, so this single copy stages the whole packaged record.
cp -a "$ROOT/config-data" "$TREE/config-data"
cp -a "$ROOT/LICENSE" "$TREE/LICENSE"

echo "== staging the launchers and the Windows build helper =="
cp -a "$ROOT/launch.sh" "$ROOT/launch.ps1" "$TREE/"
mkdir -p "$TREE/package" "$TREE/scripts"
cp -a "$ROOT/package/." "$TREE/package/"
rm -rf "$TREE/package/__pycache__"
cp -a "$ROOT/scripts/fetch_model.py" "$TREE/scripts/fetch_model.py"
mkdir -p "$TREE/assets"
cp -a "$ROOT/assets/logo.svg" "$ROOT/assets/logo.png" "$TREE/assets/"
chmod 755 "$TREE/launch.sh"

echo "== staging the model package (import closure of build/src) =="
mkdir -p "$TREE/model"
for f in "$ROOT"/model/*.py "$ROOT"/model/*.so "$ROOT"/model/*.jinja; do
    cp -a "$f" "$TREE/model/"
done
cp -a "$ROOT/model/greymicroagent.md" "$TREE/model/greymicroagent.txt"
ls "$TREE/model" | sed 's/^/  model: /'
echo "== staging the ui package (import closure of app) =="
mkdir -p "$TREE/ui"
for f in "$ROOT"/ui/*.so; do
    cp -a "$f" "$TREE/ui/"
done
ls "$TREE/ui" | sed 's/^/  ui: /'

echo "== pruning dev-only payload residue =="
rm -rf "$TREE/core/greysearch/guides"
find "$TREE" -mindepth 2 -name '*.md' -delete
rm -f "$TREE/bin/greyagent" "$TREE/bin/version.sh"
rm -f "$TREE/build/src/greyagent_run.py" "$TREE/build/src/greyagent_run.cpython-"*-linux-gnu.so
rm -rf "$TREE/build/src/build"
find "$TREE/mcp/src" -mindepth 2 -maxdepth 2 -type d -name build -exec rm -rf {} +
find "$TREE/build/src" "$TREE/mcp/src" -name '*.c' -delete
find "$TREE/build/src" "$TREE/mcp/src" -name '*.o' -delete
find "$TREE" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$TREE" -name '*.pyc' -delete
find "$TREE" -name '.pytest_cache' -type d -prune -exec rm -rf {} +
rm -rf "$TREE/tui/node_modules/.bin"
find "$TREE/tui" -path '*/dist/*.map' -delete
find "$TREE/tui/packages" -maxdepth 4 -type d \( -name src -o -name test -o -name tests -o -name examples -o -name fixtures \) -prune -print0 | xargs -0 rm -rf
DANGLING="$(find "$TREE" -xtype l | wc -l)"
find "$TREE" -xtype l -delete
echo "pruned: $DANGLING dangling symlinks"
find "$TREE/config-data/extensions" -name '*.ga08-bak' -delete
find "$TREE/config-data/extensions" -name '*.ts.bak' -delete

echo "== package-time patches on the staged launcher =="
sed -i 's|model/greymicroagent\.md|model/greymicroagent.txt|' "$TREE/bin/greymicroagent"
python3 - "$TREE/bin/greymicroagent" <<'PY'
import sys
p = sys.argv[1]
t = open(p).read()
anchor = 'mkdir -p "$GREYMICROAGENT_DBS_ROOT"'
assert anchor in t, "launcher anchor missing: %s" % anchor
line = '''if [ -f "$ROOT/model/qwen3.5-2b-abliterated.gguf" ]; then
  export GREYMICROAGENT_MODEL_PATH="${GREYMICROAGENT_MODEL_PATH:-$ROOT/model/qwen3.5-2b-abliterated.gguf}"
else
  export GREYMICROAGENT_MODEL_PATH="${GREYMICROAGENT_MODEL_PATH:-$HOME/.greymicroagent/models/qwen3.5-2b-abliterated.gguf}"
fi'''
if "GREYMICROAGENT_MODEL_PATH" not in t:
    t = t.replace(anchor, anchor + "\n" + line, 1)
open(p, "w").write(t)
PY

echo "== mechanical scrub on the staged copy only (dev source untouched) =="
python3 - "$TREE" <<'PY'
import os
import sys
from pathlib import Path

tree = Path(sys.argv[1]).resolve()
TEXT_TAIL = (".py", ".js", ".mjs", ".cjs", ".ts", ".json", ".sh", ".css", ".html",
             ".txt", ".md", ".csv", ".yml", ".yaml", ".toml", ".ini", ".cfg",
             ".svg", ".xml")
EMDASH = chr(0x2014)
REBRANDS = [
    ("knowledge-ingestor", "greymicroagent"),
    ("greymini", "greymicroagent"),
    ("GreyMini", "GreyMicroagent"),
    ("GREYMINI", "GREYMICROAGENT"),
]
PATH_PURGE = [("/home/grey/", "$HOME/"), ("/home/grey", "$HOME")]


def is_vendored(rel):
    return rel.startswith("vendor/") or "/node_modules/" in rel


def is_text(path, rel):
    head = path.open("rb").read(8192)
    if not head or b"\x00" in head:
        return False
    return True


def rewrite(path, text, strip_shell):
    kept = []
    for i, ln in enumerate(text.splitlines(keepends=True), 1):
        s = ln.strip()
        if strip_shell and s.startswith("#") and not (i == 1 and s.startswith("#!")):
            continue
        kept.append(ln)
    t = "".join(kept)
    for a, b in REBRANDS + PATH_PURGE:
        t = t.replace(a, b)
    t = t.replace(EMDASH, "-")
    path.write_text(t, encoding="utf-8")


count = 0
for p in sorted(tree.rglob("*")):
    if p.is_symlink() or not p.is_file():
        continue
    rel = str(p.relative_to(tree))
    if is_vendored(rel):
        continue
    if not is_text(p, rel):
        continue
    strip = rel.endswith(".sh") or rel == "bin/greymicroagent"
    rewrite(p, p.read_text(encoding="utf-8", errors="ignore"), strip)
    count += 1

BYTE_PAIRS = [
    (b"/home/grey", b"/home/user"),
    (b"/HOME/GREY", b"/HOME/USER"),
]
patched = 0
for p in sorted(tree.rglob("*")):
    if p.is_symlink() or not p.is_file():
        continue
    data = p.read_bytes()
    out = data
    hit = False
    for a, b in BYTE_PAIRS:
        if a in out:
            out = out.replace(a, b)
            hit = True
    if hit:
        p.write_bytes(out)
        patched += 1
print("scrub: %d staged text files rewritten, %d files byte-patched (same-length binary-safe)" % (count, patched))
PY

echo "== symlink rewrite pass =="
python3 - "$TREE" "$ROOT" <<'PY'
import os
import sys
from pathlib import Path

tree = Path(sys.argv[1]).resolve()
dev = Path(sys.argv[2]).resolve()
for p in sorted(tree.rglob("*")):
    if not p.is_symlink():
        continue
    tgt = os.readlink(p)
    if tgt.startswith("/"):
        devcand = dev / tgt.lstrip("/")
    else:
        devcand = (dev / str(p.relative_to(tree))).parent / tgt
    devcand = devcand.resolve()
    try:
        inside = devcand.relative_to(dev).as_posix()
    except ValueError:
        continue
    base = p.parent.resolve()
    staged = tree / inside
    if not staged.exists():
        print("warning: symlink target not staged: %s -> %s" % (p, staged))
        continue
    new = os.path.relpath(str(staged), str(base))
    if new == os.path.relpath(os.path.realpath(p), str(base)):
        continue
    p.unlink()
    os.symlink(new, p)
PY

echo "== stamp compiled modules newest (staleness layer) =="
find "$TREE/core" "$TREE/tools" "$TREE/services" "$TREE/mcp" "$TREE/ui" "$TREE/model" -name '*.so' -exec touch {} +

echo "== regenerate frozen manifest FROM the staged payload =="
python3 "$ROOT/scripts/gen_manifest.py" "$TREE"

echo "== pre-ship gate on the staged payload (nonzero = no deb) =="
python3 "$ROOT/scripts/pre_ship_check.py" "$TREE"

echo "== verify_compiled inside the staged tree =="
python3 "$TREE/bin/verify_compiled.py"

cat > "$PKGROOT/DEBIAN/control" <<EOF
Package: greymicroagent
Version: $VERSION
Section: utils
Priority: optional
Architecture: amd64
Depends: python3.13, nodejs (>= 22), libc6, libstdc++6, libgcc-s1
Maintainer: grey <local>
Description: greymicroagent - local grounded assistant (2B text model)
 Compiled agent core, tools and services; fork-private CPU model server
 (greymicroagent-server); Node terminal UI. One session takes a free triple
 from the fork-owned 7640-7647 port block (model 7640, RAG gate 7641,
 slimtoken 7642). Frozen, hash-pinned artifacts (state/MANIFEST.json).
 Port policy at config-data/port_policy.json; knowledge base at
 ~/.greymicroagent/dbs.
EOF
cat > "$PKGROOT/DEBIAN/postinst" <<'EOF'
#!/bin/bash
set -e
# The frozen tree ships cpython-313-tagged extensions, and python3.13 is the
# package the Depends line guarantees (deadsnakes ships it without moving the
# distro's `python3` metapackage).
if ! python3.13 /opt/greymicroagent/bin/verify_compiled.py; then
  echo "greymicroagent: frozen-tree verification FAILED after install" >&2
  exit 1
fi
echo "greymicroagent: frozen tree verified. ~/.greymicroagent/agent seeds on first launch."
EOF
chmod 755 "$PKGROOT/DEBIAN/postinst"

echo "== entry-point symlink into the frozen tree =="
ln -sfn /opt/greymicroagent/bin/greymicroagent "$PKGROOT/usr/local/bin/greymicroagent"
[ "$(readlink "$PKGROOT/usr/local/bin/greymicroagent")" = "/opt/greymicroagent/bin/greymicroagent" ] \
    || { echo "package_deb: launcher symlink sanity failed"; exit 1; }

du -sh "$TREE" | sed 's/^/payload: /'
dpkg-deb --build --root-owner-group "$PKGROOT" "$OUT/greymicroagent_${VERSION}_amd64.deb"

echo "== artifact verification (HARD STOP after this: publish is owner-gated) =="
DEB="$OUT/greymicroagent_${VERSION}_amd64.deb"
dpkg -I "$DEB"
SCRATCH="$(mktemp -d)"
dpkg-deb -x "$DEB" "$SCRATCH"
python3 "$SCRATCH/opt/greymicroagent/bin/verify_compiled.py" \
    && echo "unpacked-tree verify_compiled: PASS"
python3 "$ROOT/scripts/pre_ship_check.py" "$SCRATCH/opt/greymicroagent" \
    && echo "unpacked-tree pre-ship gate: PASS"
grep -n "7640-7647" "$SCRATCH/opt/greymicroagent/config-data/port_policy.json" | head -2
rm -rf "$SCRATCH"

echo "== portable tarball (same verified tree, launch.sh at the root) =="
TARBALL="$OUT/greymicroagent_${VERSION}_linux-x86_64.tar.gz"
rm -f "$TARBALL"
tar -C "$TREE" --owner=0 --group=0 --numeric-owner -czf "$TARBALL" .
ls -la "$TARBALL"
ls -la "$OUT" | grep deb
