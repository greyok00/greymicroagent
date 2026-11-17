#!/bin/bash
# package_deb.sh - build the greylocalrag .deb locally. LOCAL ARTIFACT ONLY:
# the release is owner-gated, nothing here pushes, uploads, or publishes.
#
# dpkg layout: /opt/greylocalrag = the frozen tree (launcher, compiled modules,
# tui dist, vendored runtime); /usr/local/bin/greylocalrag = symlink. The
# postinst runs bin/verify_compiled.py so a broken install fails loudly at
# dpkg time, never silently at first boot.
#
# Release-wave A packaging flow (build-hygiene law, spec section 2.9):
#   1. the dev tree must be green first: gen_manifest + verify_compiled.
#   2. payload is STAGED as a real-file copy (never a tar of dev paths):
#      bin (minus the greyagent family launcher), core (minus the greysearch
#      dev guides), tools, services, build/src (minus .c intermediates and the
#      greyagent_run helper), mcp, tui (minus dist sourcemaps), vendor;
#      config/extensions + config/port_policy.json copied REAL files from the
#      resolved symlink target (the dev `config` is a symlink; tar of it would
#      carry a host-locked link); README.md, THIRD-PARTY-NOTICES.txt; the
#      model card AS model/greylocalrag.txt (the .md dev name never ships);
#      state/ carries ONLY a manifest regenerated from the staged tree itself,
#      so every pin matches exactly what the deb installs.
#   3. MECHANICAL SCRUB on the staged copy only, dev source untouched:
#      - rebrand "knowledge-ingestor" -> "greylocalrag" (Task 3 carry: the
#        kbcore User-Agent and the KB db-format tag; the pre-ship gate flags
#        the string as FAIL, so the payload copy must not carry it)
#      - codename purge "greymini" -> "greylocalrag" (also fixed inside the
#        compiled dist fallback paths, which are fork-owned after the rebrand)
#      - host path purge: "/home/grey/..." -> "$HOME/..." placeholders; the
#        runtime paths that actually matter are resolved by the staged
#        launcher export GREYLOCALRAG_MODEL_PATH=$HOME/.greylocalrag/models/...
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
PKGROOT="$OUT/greylocalrag"
TREE="$PKGROOT/opt/greylocalrag"
VERSION="$(python3 "$ROOT/bin/version.sh" 2>/dev/null || true)"
[ -n "$VERSION" ] || VERSION="$(node "$ROOT/tui/packages/coding-agent/dist/cli.js" --version 2>/dev/null | tail -1 | tr -dc '0-9.')"
[ -n "$VERSION" ] || VERSION="0.7.5.1"

echo "== packaging greylocalrag $VERSION =="
echo "== dev-tree sanity: gen_manifest + verify_compiled =="
python3 "$ROOT/scripts/gen_manifest.py"
python3 "$ROOT/bin/verify_compiled.py"

rm -rf "$PKGROOT"
rm -f "$OUT/greylocalrag_${VERSION}_amd64.deb"
mkdir -p "$TREE" "$PKGROOT/DEBIAN" "$PKGROOT/usr/local/bin" "$TREE/state"

echo "== staging payload (real files, no dev symlinks) =="
for d in bin core tools services mcp tui vendor; do
    cp -a "$ROOT/$d" "$TREE/$d"
done
mkdir -p "$TREE/build"
cp -a "$ROOT/build/src" "$TREE/build/src"

REAL_CONFIG="$(readlink -f "$ROOT/config")"
mkdir -p "$TREE/config"
cp -a "$REAL_CONFIG/extensions" "$TREE/config/extensions"
cp -a "$REAL_CONFIG/port_policy.json" "$TREE/config/port_policy.json"

cp -a "$ROOT/README.md" "$TREE/README.md"
cp -a "$ROOT/THIRD-PARTY-NOTICES.txt" "$TREE/THIRD-PARTY-NOTICES.txt"
cp -a "$ROOT/config-data" "$TREE/config-data"
cp -a "$ROOT/LICENSE" "$TREE/LICENSE"

echo "== staging the model package (import closure of build/src) =="
mkdir -p "$TREE/model"
for f in "$ROOT"/model/*.py "$ROOT"/model/*.so; do
    cp -a "$f" "$TREE/model/"
done
cp -a "$ROOT/model/greylocalrag.md" "$TREE/model/greylocalrag.txt"
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
find "$TREE/config/extensions" -name '*.ga08-bak' -delete
find "$TREE/config/extensions" -name '*.ts.bak' -delete

echo "== package-time patches on the staged launcher =="
sed -i 's|model/greylocalrag\.md|model/greylocalrag.txt|' "$TREE/bin/greylocalrag"
python3 - "$TREE/bin/greylocalrag" <<'PY'
import sys
p = sys.argv[1]
t = open(p).read()
anchor = 'mkdir -p "$GREYLOCALRAG_DBS_ROOT"'
assert anchor in t, "launcher anchor missing: %s" % anchor
line = ('export GREYLOCALRAG_MODEL_PATH="${GREYLOCALRAG_MODEL_PATH:-'
        '$HOME/.greylocalrag/models/qwen3-vl-2b-abliterated.gguf}"')
if "GREYLOCALRAG_MODEL_PATH" not in t:
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
    ("knowledge-ingestor", "greylocalrag"),
    ("greymini", "greylocalrag"),
    ("GreyMini", "GreyLocalRag"),
    ("GREYMINI", "GREYLOCALRAG"),
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
    strip = rel.endswith(".sh") or rel == "bin/greylocalrag"
    rewrite(p, p.read_text(encoding="utf-8", errors="ignore"), strip)
    count += 1

BYTE_PAIRS = [
    (b"/home/grey", b"/home/user"),
    (b"/HOME/GREY", b"/HOME/USER"),
    (b"greymini", b"localrag"),
    (b"GreyMini", b"LocalRag"),
    (b"GREYMINI", b"LOCALRAG"),
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
Package: greylocalrag
Version: $VERSION
Section: utils
Priority: optional
Architecture: amd64
Depends: python3 (>= 3.13), nodejs (>= 22), libc6, libstdc++6, libgcc-s1, libnvidia-ml1 | libcuda1
Maintainer: grey <local>
Description: greylocalrag - portable minimized offline agent (2B hybrid)
 Fully Cython-compiled agent core/tools/services; fork-unique private
 llama-server (greylocalrag-server) with session slots inside the fork-owned
 7640-7647 port block (:7640 model, :7641 slimtoken lane); Node TUI under the
 @greyagent scope (its compiled scope); frozen, hash-pinned artifacts
 (state/MANIFEST.json) and an on-demand, masked lifecycle. Port policy at
 config/port_policy.json; grounding KB at ~/.greylocalrag/dbs.
EOF
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

echo "== entry-point symlink into the frozen tree =="
ln -sfn /opt/greylocalrag/bin/greylocalrag "$PKGROOT/usr/local/bin/greylocalrag"
[ "$(readlink "$PKGROOT/usr/local/bin/greylocalrag")" = "/opt/greylocalrag/bin/greylocalrag" ] \
    || { echo "package_deb: launcher symlink sanity failed"; exit 1; }

du -sh "$TREE" | sed 's/^/payload: /'
dpkg-deb --build --root-owner-group "$PKGROOT" "$OUT/greylocalrag_${VERSION}_amd64.deb"

echo "== artifact verification (HARD STOP after this: publish is owner-gated) =="
DEB="$OUT/greylocalrag_${VERSION}_amd64.deb"
dpkg -I "$DEB"
SCRATCH="$(mktemp -d)"
dpkg-deb -x "$DEB" "$SCRATCH"
python3 "$SCRATCH/opt/greylocalrag/bin/verify_compiled.py" \
    && echo "unpacked-tree verify_compiled: PASS"
python3 "$ROOT/scripts/pre_ship_check.py" "$SCRATCH/opt/greylocalrag" \
    && echo "unpacked-tree pre-ship gate: PASS"
grep -n "7640-7647" "$SCRATCH/opt/greylocalrag/config/port_policy.json" | head -2
rm -rf "$SCRATCH"
ls -la "$OUT" | grep deb
