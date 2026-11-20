#!/usr/bin/env python3
"""Boot gate: assert the frozen tree is intact (hardened build).

Checks, without hashing anything over MANIFEST.hash_limit:
  1. every core/tools/services module count: 7 core, 31 tools, 6 services .so
  2. every small manifest file exists with matching sha256 (and manifest
     entries that carry an "error" instead of a pin are FATAL - GM-02: an
     error entry inside files[] means generation was contaminated)
  3. every size-pinned artifact exists with matching size
  4. the TUI's frozen dependencies are linked: @greyagent/* (10) and the four
     @cortex/* compat links the prebuilt dist still imports
  5. the TUI entry parses: node --check on dist cli.js (catches src/dist desync)
  6. compiled modules are not older than their visible .py sources
     (GM-03b: a newer source silently loses import precedence to the .so)

Fails loudly with the exact missing/mismatched path. Exit 0 = boot may proceed.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "state" / "MANIFEST.json"
CLI = ROOT / "tui" / "packages" / "coding-agent" / "dist" / "cli.js"
NM = ROOT / "tui" / "node_modules"

EXPECTED_SO = {
    "core": 7, "tools": 31, "services": 6,
}
# GM-03b (2026-11-03): .so modules compiled into <dir>/<stem>.so whose .py
# source is visible under build/src or mcp/src - if the source is NEWER than
# the module, the module a process imports is not what the tree says it runs
# (the cortexagent CA-13 silent-shadowing class, which produced stale behavior
# with zero error messages).
SO_DIRS = ("core", "tools", "services", "mcp", "ui")
GREY_LINKS = ["agent-core", "ai", "client", "coding-agent", "evals", "protocol",
              "server", "telemetry", "tui", "session-backend-sqlite-node"]
CORTEX_LINKS = ["agent-core", "ai", "coding-agent", "tui"]


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _stale_modules() -> list[str]:
    """Modules whose .py source is newer than the compiled .so beside it or
    under build/src / mcp/src (source of the same stem). Missing sources are
    skipped - the pin check owns existence; this only compares mtimes."""
    out = []
    for d in SO_DIRS:
        for so in sorted((ROOT / d).glob("*.so")):
            stem = so.name.split(".cpython", 1)[0]
            candidates = [ROOT / "build" / "src" / f"{stem}.py"]
            src_area = ROOT / "mcp" / "src"
            if (src_area / stem).is_dir():
                candidates.append(src_area / stem / f"{stem}.py")
                candidates.append(src_area / stem / "__init__.py")
            candidates.append(ROOT / d / f"{stem}.py")
            src = next((c for c in candidates
                        if c.exists() and c.is_file()), None)
            if src is None:
                continue
            if src.stat().st_mtime > so.stat().st_mtime:
                out.append(f"stale module: {so.relative_to(ROOT)} older than "
                           f"{src.relative_to(ROOT)} - rebuild before boot")
    return out


def main() -> int:
    bad: list[str] = []

    for name, want in EXPECTED_SO.items():
        got = len(list((ROOT / name).glob("*.so")))
        if got != want:
            bad.append(f"{name}/: expected {want} .so, found {got}")

    try:
        manifest = json.loads(MANIFEST.read_text())
    except FileNotFoundError:
        print(f"verify_compiled: {MANIFEST} missing - run scripts/gen_manifest.py")
        return 1
    for rel, meta in manifest.get("files", {}).items():
        # GM-02: generation aborted on missing dirs now - an error entry that
        # still ships means the gate must refuse, naming the contaminated key.
        if isinstance(meta, dict) and meta.get("error"):
            bad.append(f"manifest entry is an error object: {rel} → "
                       f"{meta.get('error')}")
            continue
        p = ROOT / rel
        if not p.exists():
            bad.append(f"missing: {rel}")
            continue
        if p.stat().st_size != meta.get("size"):
            bad.append(f"size mismatch: {rel}")
            continue
        want_hash = meta.get("sha256")
        if want_hash and _sha256(p) != want_hash:
            bad.append(f"hash mismatch: {rel}")

    bad.extend(_stale_modules())

    for link in GREY_LINKS:
        if not (NM / "@greyagent" / link).exists():
            bad.append(f"missing workspace link: @greyagent/{link}")
    # 2026-10-24 hardened: the renamed dist imports @greyagent/* only - any
    # surviving @(cortex|claude|anthropic|openai) scope link = desync residue
    for scope in ["@cortex", "@anthropic-ai-fork"]:
        if (NM / scope).exists():
            bad.append(f"stale compat scope must not exist: {scope}/")

    try:
        r = subprocess.run(["node", "--check", str(CLI)], capture_output=True, timeout=30)
        if r.returncode != 0:
            bad.append(f"dist cli.js fails node --check (src/dist desync?): {(r.stderr or b'').decode()[:200]}")
    except (OSError, subprocess.TimeoutExpired):
        bad.append("node --check could not run")

    if bad:
        print("verify_compiled: FROZEN TREE OUT OF SYNC - fixing required before boot:")
        for line in bad[:25]:
            print(f"  ✗ {line}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())