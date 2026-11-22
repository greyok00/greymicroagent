"""Portable document parser (Windows source fallback).

PDF text comes from pymupdf when present, then pypdf. Plain text files are
read directly. The result never claims content that was not extracted.
"""
from __future__ import annotations

from pathlib import Path


def _pdf_text(path: Path) -> str:
    try:
        import fitz  # pymupdf

        with fitz.open(path) as doc:
            return "\n".join(page.get_text() for page in doc)
    except Exception:
        pass
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:
        raise RuntimeError("no PDF reader available: %s" % exc)


def parse_document(file: str = "", path: str = "", **kw) -> dict:
    target = file or path or kw.get("filename") or ""
    if not target:
        return {"ok": False, "output": "", "error": "missing argument: file"}
    p = Path(str(target)).expanduser()
    if not p.is_file():
        return {"ok": False, "output": "", "error": "not a file: %s" % p}
    try:
        text = _pdf_text(p) if p.suffix.lower() == ".pdf" else p.read_text(
            encoding="utf-8", errors="replace")
    except Exception as exc:
        return {"ok": False, "output": "", "error": str(exc)[:400]}
    return {"ok": True, "output": text[:100000],
            "error": "", "chars": len(text)}
