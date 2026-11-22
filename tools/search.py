"""Portable file glob and grep tools (Windows source fallback)."""
from __future__ import annotations

import re
from pathlib import Path


def _base(base) -> Path:
    return Path(str(base or ".")).expanduser()


def glob(pattern: str = "", base: str = ".", **kw) -> dict:
    if not pattern:
        return {"ok": False, "output": "", "error": "missing argument: pattern"}
    root = _base(base)
    try:
        hits = sorted(str(p) for p in root.glob(pattern))
    except (OSError, ValueError) as exc:
        return {"ok": False, "output": "", "error": str(exc)}
    return {"ok": True, "output": "\n".join(hits[:2000]), "error": ""}


def grep(pattern: str = "", base: str = ".", glob_filter: str = "", **kw) -> dict:
    if not pattern:
        return {"ok": False, "output": "", "error": "missing argument: pattern"}
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        return {"ok": False, "output": "", "error": "bad pattern: %s" % exc}
    root = _base(base)
    name_filter = glob_filter or "*"
    out = []
    try:
        for path in root.rglob(name_filter):
            if not path.is_file():
                continue
            try:
                if path.stat().st_size > 2_000_000:
                    continue
                data = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for number, line in enumerate(data.splitlines(), 1):
                if rx.search(line):
                    out.append("%s:%d:%s" % (path, number, line[:300]))
                    if len(out) >= 500:
                        break
            if len(out) >= 500:
                break
    except OSError as exc:
        return {"ok": False, "output": "", "error": str(exc)}
    return {"ok": True, "output": "\n".join(out), "error": ""}
