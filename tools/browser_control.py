"""Portable browser control boundary (Windows source fallback)."""
from __future__ import annotations


def fill_and_send(tab=None, text: str = "", iframe_marker: str = "",
                  submit: bool = True):
    from tools import browser_tools
    result = browser_tools._fill_send(
        text=text, tab=tab, iframe_marker=iframe_marker or "", submit=bool(submit))
    if not result.get("ok"):
        raise RuntimeError(result.get("error") or "fill failed")
    return result.get("output", "")
