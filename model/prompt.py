"""System prompt loader.

GM-08/GM-22 (2026-11-03): the mini prompt is model/greymini.md — the retired
model/system-prompt.txt (parent fork's file, removed in commit abd7b233) was
still the compiled module's dependency, so every import of model.prompt
crashed at module level and took core.loop / wiring / ui.app down with it.
Now the loader is fail-open: a missing prompt file can never brick an import
again, it degrades to a one-line stand-in instead.
"""
from __future__ import annotations

from pathlib import Path

PROMPT_FILE = Path(__file__).resolve().parent / "greymini.md"

_FILE_MISSING = (
    "greymini, local agent on this machine. Operator speaks with you "
    "directly. State the outcome first, then reasoning."
)


def load_system_prompt() -> str:
    try:
        return PROMPT_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return _FILE_MISSING


def reload_system_prompt() -> str:
    global SYSTEM_PROMPT
    SYSTEM_PROMPT = load_system_prompt()
    return SYSTEM_PROMPT


SYSTEM_PROMPT = load_system_prompt()