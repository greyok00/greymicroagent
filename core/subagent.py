"""Portable subagent used by the spawn_subagent tool."""
from __future__ import annotations

from core import llm


def spawn(prompt: str = "", **kw) -> dict:
    text = str(prompt or "").strip()
    if not text:
        return {"ok": False, "output": "", "error": "missing argument: prompt"}
    try:
        answer = llm._query_llm(
            [{"role": "user", "content": text}],
            timeout=int(kw.get("timeout") or 600),
        )
    except Exception as exc:
        return {"ok": False, "output": "", "error": "subagent failed: %s" % str(exc)[:400]}
    return {"ok": True, "output": answer, "error": ""}
