"""Portable Chrome tools (Windows source fallback).

A single headless Chromium page is kept open lazily through patchright, which
ships its own browser. Every tool maps onto that page. Failures are reported
with the real exception, never as fabricated content.
"""
from __future__ import annotations

import atexit
import json
import threading
import time

_state = {"pw": None, "browser": None, "page": None, "latency": [], "reconnects": 0}
_lock = threading.Lock()


def _page():
    with _lock:
        if _state["page"] is not None and not _state["page"].is_closed():
            return _state["page"]
        from patchright.sync_api import sync_playwright

        if _state["browser"] is None or not _state["browser"].is_connected():
            _state["pw"] = _state["pw"] or sync_playwright().start()
            _state["browser"] = _state["pw"].chromium.launch(headless=True)
            _state["reconnects"] += 1
        _state["page"] = _state["browser"].new_page()
        return _state["page"]


def _timed(fn):
    started = time.time()
    try:
        return fn()
    finally:
        _state["latency"].append(time.time() - started)
        _state["latency"] = _state["latency"][-20:]


def _ok(payload) -> dict:
    return {"ok": True, "output": json.dumps(payload, ensure_ascii=False, default=str),
            "error": ""}


def _err(exc) -> dict:
    return {"ok": False, "output": "", "error": "%s: %s" % (type(exc).__name__, str(exc)[:400])}


def _target_page(tab=None):
    page = _page()
    if tab:
        pages = page.context.pages
        for candidate in pages:
            if str(tab) in (candidate.url or ""):
                return candidate
    return page


def _navigate(url: str = "", tab=None, **kw) -> dict:
    target = str(url or kw.get("page") or "")
    if not target.startswith(("http://", "https://")):
        return {"ok": False, "output": "", "error": "chrome_navigate needs an http(s) url"}
    try:
        page = _target_page(tab)
        _timed(lambda: page.goto(target, wait_until="domcontentloaded", timeout=60000))
        return _ok({"title": page.title(), "url": page.url})
    except Exception as exc:
        return _err(exc)


def _tabs(**kw) -> dict:
    try:
        page = _page()
        return _ok([{"index": i, "title": p.title(), "url": p.url}
                    for i, p in enumerate(page.context.pages)])
    except Exception as exc:
        return _err(exc)


def _fetch(url: str = "", selector: str = "body", wait_for_text: str = "",
           timeout: float = 30, tab=None, **kw) -> dict:
    if not url:
        return {"ok": False, "output": "", "error": "missing argument: url"}
    try:
        page = _target_page(tab)
        _timed(lambda: page.goto(url, wait_until="domcontentloaded",
                                 timeout=int(float(timeout) * 1000) or 30000))
        if wait_for_text:
            page.wait_for_function(
                "t => document.body && document.body.innerText.includes(t)",
                arg=str(wait_for_text), timeout=int(float(timeout) * 1000) or 30000)
        text = page.locator(selector or "body").first.inner_text(timeout=15000)
        return _ok({"url": page.url, "title": page.title(), "text": text[:40000]})
    except Exception as exc:
        return _err(exc)


def _click(target: str = "", by_text: bool = False, timeout: float = 10, tab=None, **kw) -> dict:
    if not target:
        return {"ok": False, "output": "", "error": "missing argument: target"}
    try:
        page = _target_page(tab)
        millis = int(float(timeout or 10) * 1000)
        if by_text:
            locator = page.get_by_text(str(target), exact=False).first
        else:
            locator = page.locator(str(target)).first
        _timed(lambda: locator.click(timeout=millis))
        return _ok({"clicked": target, "url": page.url, "title": page.title()})
    except Exception as exc:
        return _err(exc)


def _type(target: str = "", text: str = "", by_text: bool = False, submit: bool = False,
          timeout: float = 10, tab=None, **kw) -> dict:
    if not target:
        return {"ok": False, "output": "", "error": "missing argument: target"}
    try:
        page = _target_page(tab)
        millis = int(float(timeout or 10) * 1000)
        if by_text:
            locator = page.get_by_text(str(target), exact=False).first
        else:
            locator = page.locator(str(target)).first
        _timed(lambda: locator.fill(str(text or ""), timeout=millis))
        if submit:
            locator.press("Enter")
        return _ok({"typed_into": target, "chars": len(str(text or "")), "url": page.url})
    except Exception as exc:
        return _err(exc)


def _evaluate(expression: str = "", timeout: float = 10, tab=None, **kw) -> dict:
    if not expression:
        return {"ok": False, "output": "", "error": "missing argument: expression"}
    try:
        page = _target_page(tab)
        value = _timed(lambda: page.evaluate(str(expression)))
        return _ok({"result": value})
    except Exception as exc:
        return _err(exc)


def _snapshot(depth=None, tab=None, **kw) -> dict:
    try:
        page = _target_page(tab)
        try:
            value = page.accessibility.snapshot()
        except Exception:
            value = None
        if value is None:
            value = {"text": page.inner_text("body")[:20000]}
        return _ok({"url": page.url, "title": page.title(), "snapshot": value})
    except Exception as exc:
        return _err(exc)


def _fill_send(text: str = "", iframe_marker: str = "", tag: str = "TEXTAREA",
               class_fragment: str = "", submit: bool = True, tab=None, **kw) -> dict:
    if not text:
        return {"ok": False, "output": "", "error": "missing argument: text"}
    try:
        page = _target_page(tab)
        frame = page.main_frame
        if iframe_marker:
            for candidate in page.frames:
                if iframe_marker in (candidate.url or ""):
                    frame = candidate
                    break
            else:
                return {"ok": False, "output": "",
                        "error": "no iframe whose src contains %r" % iframe_marker}
        selector = str(tag or "TEXTAREA").lower()
        if class_fragment:
            selector += "." + str(class_fragment)
        locator = frame.locator(selector).first
        locator.fill(str(text))
        if submit:
            locator.press("Enter")
        return _ok({"filled": selector, "chars": len(str(text)),
                    "submitted": bool(submit), "url": page.url})
    except Exception as exc:
        return _err(exc)


def _health(**kw) -> dict:
    page = _state["page"]
    open_pages = 0
    if page is not None and not page.is_closed():
        try:
            open_pages = len(page.context.pages)
        except Exception:
            open_pages = 1
    average = (sum(_state["latency"]) / len(_state["latency"])) if _state["latency"] else 0.0
    return _ok({"cdp": bool(page is not None and not page.is_closed()),
                "tabs": open_pages, "reconnects": _state["reconnects"],
                "avg_latency_s": round(average, 3)})


def _status(**kw) -> dict:
    return _health(**kw)


def _shutdown():
    try:
        if _state["browser"] is not None:
            _state["browser"].close()
    except Exception:
        pass
    try:
        if _state["pw"] is not None:
            _state["pw"].stop()
    except Exception:
        pass
    _state.update(pw=None, browser=None, page=None)


atexit.register(_shutdown)


def register_browser_tools() -> int:
    from core import registry
    from core.registry import _schema

    registry.register_tool("chrome_status", _schema(
        "State of the headless browser and open tabs.", {}, []), _status)
    registry.register_tool("chrome_tabs", _schema(
        "List open tabs (index, title, url).", {}, []), _tabs)
    registry.register_tool("chrome_navigate", _schema(
        "Open one http(s) page in the headless browser. args: url, tab.",
        {"url": {"type": "string"}, "tab": {"type": "string"}}, ["url"]), _navigate)
    registry.register_tool("chrome_fetch", _schema(
        "Navigate and return page text (JS-heavy sites). args: url, selector.",
        {"url": {"type": "string"}, "selector": {"type": "string"},
         "wait_for_text": {"type": "string"}, "timeout": {"type": "number"},
         "tab": {"type": "string"}}, ["url"]), _fetch)
    registry.register_tool("chrome_click", _schema(
        "Click by CSS selector or visible text. args: target, by_text.",
        {"target": {"type": "string"}, "by_text": {"type": "boolean"},
         "timeout": {"type": "number"}, "tab": {"type": "string"}}, ["target"]), _click)
    registry.register_tool("chrome_type", _schema(
        "Type into an element. args: target, text, by_text, submit.",
        {"target": {"type": "string"}, "text": {"type": "string"},
         "by_text": {"type": "boolean"}, "submit": {"type": "boolean"},
         "timeout": {"type": "number"}, "tab": {"type": "string"}},
        ["target", "text"]), _type)
    registry.register_tool("chrome_evaluate", _schema(
        "Evaluate JavaScript in the page and return its JSON value. args: expression.",
        {"expression": {"type": "string"}, "timeout": {"type": "number"},
         "tab": {"type": "string"}}, ["expression"]), _evaluate)
    registry.register_tool("chrome_snapshot", _schema(
        "Accessibility snapshot of the open page. args: depth, tab.",
        {"depth": {"type": "number"}, "tab": {"type": "string"}}, []), _snapshot)
    registry.register_tool("chrome_fill_send", _schema(
        "Fill a shadow-DOM composer and optionally press Enter. args: text, "
        "iframe_marker, tag, class_fragment, submit.",
        {"text": {"type": "string"}, "iframe_marker": {"type": "string"},
         "tag": {"type": "string"}, "class_fragment": {"type": "string"},
         "submit": {"type": "boolean"}, "tab": {"type": "string"}},
        ["text"]), _fill_send)
    registry.register_tool("chrome_health", _schema(
        "Browser engine health: reachability, tabs, latency.", {}, []), _health)
    return 10
