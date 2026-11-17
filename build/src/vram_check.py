#!/usr/bin/env python3
"""VRAM interlock (hardened build, owner order 2026-10-24).

Before greyagent spawns its model, check that no OTHER compute process holds
the GPU. If it does, print a plain refusal naming the holder and exit 1 —
the launcher boots the TUI anyway and shows the situation in the status line;
it must never silently OOM-fight another agent (cortexagent's 35B and this
27B both want the full GPU, `-ngl 999`/`-ngl -1`).

Exit codes: 0 = GPU free, 1 = held (details on stdout).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

# memory below this is driver/desktop residue, not a competing model
_IGNORE_MB = 1024


def held_by() -> list[tuple[int, str, int]]:
    """Return [(pid, name, used_mb)] of other GPU compute processes."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    rows = []
    for line in (out.stdout or "").strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 3 or not parts[0].isdigit():
            continue
        pid, name, mb = int(parts[0]), parts[1], int(parts[2])
        if mb >= _IGNORE_MB:
            rows.append((pid, name, mb))
    return rows


def _is_greylocalrag(pid: int) -> bool:
    """True when the holder is one of OUR OWN instances (owner 2026-10-25:
    "don't ruin the current running one" — sibling greylocalrag sessions share the
    card, one instance's boot must never refuse because of another's model).
    Family test = the real executable path of the holder."""
    try:
        exe = os.path.realpath(f"/proc/{pid}/exe")
    except OSError:
        return False
    return exe.endswith("/greylocalrag-server") or "/greylocalrag/vendor/" in exe


def main() -> int:
    holders = [h for h in held_by() if not _is_greylocalrag(h[0])]
    if not holders:
        return 0
    for pid, name, mb in holders:
        print(f"GPU held by pid {pid} ({name}) using {mb} MiB — stop it before loading this model")
    return 1


if __name__ == "__main__":
    sys.exit(main())