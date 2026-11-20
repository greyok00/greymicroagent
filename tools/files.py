"""Portable file tools (Windows source fallback for the compiled module)."""
from __future__ import annotations

from pathlib import Path


def _p(path) -> Path:
    return Path(str(path or "")).expanduser()


def read_file(path: str = "", **kw) -> dict:
    p = _p(path)
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"ok": False, "output": "", "error": str(exc)}
    return {"ok": True, "output": text[:200000], "error": ""}


def write_file(path: str = "", content: str = "", **kw) -> dict:
    p = _p(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(content or ""), encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "output": "", "error": str(exc)}
    return {"ok": True, "output": "wrote %d bytes to %s" % (len(str(content or "")), p), "error": ""}


def edit_file(path: str = "", old: str = "", new: str = "", **kw) -> dict:
    p = _p(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "output": "", "error": str(exc)}
    if old not in text:
        return {"ok": False, "output": "", "error": "old text not found in %s" % p}
    updated = text.replace(old, str(new or ""), 1)
    try:
        p.write_text(updated, encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "output": "", "error": str(exc)}
    return {"ok": True, "output": "edited %s" % p, "error": ""}


def list_dir(path: str = "", **kw) -> dict:
    p = _p(path or ".")
    try:
        entries = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
    except OSError as exc:
        return {"ok": False, "output": "", "error": str(exc)}
    lines = [e.name + ("/" if e.is_dir() else "") for e in entries]
    return {"ok": True, "output": "\n".join(lines), "error": ""}


def delete_file(path: str = "", **kw) -> dict:
    p = _p(path)
    try:
        if p.is_dir():
            p.rmdir()
        else:
            p.unlink()
    except OSError as exc:
        return {"ok": False, "output": "", "error": str(exc)}
    return {"ok": True, "output": "deleted %s" % p, "error": ""}
