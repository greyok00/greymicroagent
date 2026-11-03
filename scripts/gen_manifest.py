#!/usr/bin/env python3
"""Generate MANIFEST.json — the source-of-truth inventory of the frozen tree.

Small files get sha256 (checked every boot); heavy files (models, wheels)
are pinned by exact size only (hashing 13+ GB would slow every boot) and can
be hash-checked with --full. Regenerate after ANY artifact change, then run
bin/verify_compiled.py — a boot must never carry a stale manifest.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_HASH_BYTES = 64 * 1024 * 1024  # hash everything below this; size-pin above

WALK_DIRS = ["mcp",
             "core", "tools", "services", "build/src", "vendor/slimtoken/src/slimtoken",
             "vendor/llamacpp", "vendor/greymini-server",
             "tui/packages/agent/dist", "tui/packages/ai/dist", "tui/packages/client/dist",
             "tui/packages/coding-agent/dist", "tui/packages/protocol/dist", "tui/packages/server/dist",
             "tui/packages/session-backends/sqlite-node/dist",
             # 2026-10-31 QA (GP-02 class): TS extensions and bin launchers are
             # runtime load-bearing. (The "greypentest" entry added 2026-10-31
             # stays out: this fork does NOT vendor the greypentest MCP package —
             # its registry spawns the standalone tree at /home/grey/greypentest,
             # so there is nothing to pin here and pinning would demand a dir
             # that legitimately never exists.)
             "config/extensions", "bin"]

# GM-21 (2026-11-03): runtime-mutatable data must never be a frozen pin —
# mcp/data/ is written by the MCP servers at work time (asvs-seed.json was
# grown in place by the ASVS merge and its stale 2453 B pin BRICKED every
# boot). Unpinned = the gate watches code, not work products.
EXCLUDE_PREFIXES = ("mcp/data/",)


def _sha256(p: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _derived(p: Path, root: Path) -> bool:
    """Derived/generated artifacts are not frozen pins: cython .c intermediates,
    scratch build dirs, object files, caches."""
    # rglob hands back ABSOLUTE paths — anchor everything to the tree root or
    # the prefix/parts checks below would never fire (GM-21 lesson, same
    # silent-no-op class as the audit's own findings).
    rel = p.relative_to(root).as_posix()
    if rel.startswith(EXCLUDE_PREFIXES):
        return True
    if p.suffix in {".o", ".c", ".bak", ".pyc", ".log"}:
        return True
    if p.name.endswith(("-bak", ".mangled", ".regenerated", ".so-old")):
        return True
    # runtime residue (live logging) must not become a frozen pin.
    # GM-03a (2026-11-03): "build" is REMOVED from this set — build/src holds
    # the .py sources of every compiled module AND the launcher's server.py,
    # which the manifest is supposed to pin; the old parts-check silently
    # unpinned the entire walked build/src entry while it looked pinned.
    # Cython intermediates are covered by the suffix check above.
    parts = rel.split("/")
    if any(part in {"__pycache__", "logs"} for part in parts):
        return True
    # GM-21: cython SCRATCH dirs are named "build" inside the source trees
    # (build/src/build/x.so, mcp/src/<name>/build/...) — exclude those, but
    # NEVER inside vendor/ (the vendored engine ships real libs in build/).
    if "vendor" not in parts and "build" in parts[2:] and parts[0] == "build":
        return True
    if "vendor" not in parts and "build" in parts[1:] and parts[0] == "mcp":
        return True
    return False


def main() -> int:
    out = {}
    for d in WALK_DIRS:
        base = ROOT / d
        # GM-02 (2026-11-03): a missing curated walk dir used to become an
        # {"error": "MISSING DIRECTORY"} entry INSIDE files[] — which the gate
        # then read as a missing FILE — silently shipping a smaller frozen set.
        # A missing curated dir is a misconfiguration: abort without writing.
        if not base.exists():
            print(f"gen_manifest: curated walk dir missing: {d} — fixing the "
                  "tree or removing it from WALK_DIRS; NOT writing a "
                  "silently-smaller manifest", file=sys.stderr)
            return 1
        for p in sorted(base.rglob("*")):
            if not p.is_file() or _derived(p, ROOT):
                continue
            rel = str(p.relative_to(ROOT))
            try:
                size = p.stat().st_size
            except OSError:
                continue
            if size > MAX_HASH_BYTES:
                out[rel] = {"size": size}
            else:
                out[rel] = {"size": size, "sha256": _sha256(p)}
    manifest = {
        "name": "greymini-hardened",
        "format": 1,
        "hashed_below": MAX_HASH_BYTES,
        "files": out,
    }
    path = ROOT / "state" / "MANIFEST.json"
    path.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    print(f"MANIFEST: {len(out)} files -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())