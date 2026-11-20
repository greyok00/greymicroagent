"""Portable conversation mode classifier used by the agent loop."""
from __future__ import annotations


def classify_mode(text: str) -> str:
    low = (text or "").lower()
    if any(word in low for word in ("/rag", "ingest", "knowledge base", "documents")):
        return "rag"
    if any(word in low for word in ("search", "research", "look up", "find out")):
        return "research"
    if any(word in low for word in ("code", "script", "bug", "fix", "build")):
        return "code"
    return "chat"
