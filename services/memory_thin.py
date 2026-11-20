"""Portable hot-memory store (Windows source fallback).

One JSONL file per product under the memory home, matching the format the
compiled module writes: {"role", "content", "timestamp"}.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path


def _root() -> Path:
    base = (os.environ.get("GREYAGENT_MEMORY_DIR")
            or os.environ.get("CORTEXAGENT_MEMORY_DIR")
            or str(Path.home() / ".greymicroagent" / "memory"))
    return Path(base).expanduser()


def _hot() -> Path:
    name = (os.environ.get("GREYAGENT_PLATFORM") or "greymicroagent") + ".jsonl"
    folder = _root() / "hot"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / name


def _entries() -> list:
    path = _hot()
    out = []
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if isinstance(row, dict):
                out.append(row)
    except OSError:
        return []
    return out


def append(content: str = "", role: str = "user", **kw) -> str:
    text = str(content or "").strip()
    if not text:
        return "nothing to save"
    row = {"role": str(role or "user"), "content": text,
           "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")}
    with _hot().open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return "saved %d chars" % len(text)


def read_last(n: int = 5, **kw) -> list:
    count = max(1, min(int(n or 5), 100))
    return _entries()[-count:]


def search(query: str = "", **kw) -> str:
    needle = str(query or "").strip().lower()
    if not needle:
        return json.dumps([])
    hits = [row for row in _entries()
            if needle in str(row.get("content", "")).lower()][-50:]
    return json.dumps(hits, ensure_ascii=False)


def write_cold(**kw) -> int:
    rows = _entries()
    if not rows:
        return 0
    cold = _root() / "cold"
    cold.mkdir(parents=True, exist_ok=True)
    target = cold / ("snapshot-%s.jsonl" % time.strftime("%Y%m%d-%H%M%S"))
    target.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                      encoding="utf-8")
    return len(rows)
