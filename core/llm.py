"""Portable model client used on platforms without the compiled core.

The full build compiles this module; the source here keeps the same small
surface the tool layer uses: LAST_TPS, USAGE, and the two query helpers.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request

LAST_TPS = 0.0
USAGE = {"calls": 0, "tokens": 0}


def _base() -> str:
    return (os.environ.get("GREYAGENT_LOCAL_BASE")
            or "http://127.0.0.1:7641/v1").rstrip("/")


def _post(path: str, body: dict, timeout: int) -> dict:
    req = urllib.request.Request(
        _base() + path,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _query_llm(messages, timeout: int = 600, **kw) -> str:
    global LAST_TPS
    started = time.time()
    data = _post("/chat/completions", {
        "model": "greymicroagent",
        "messages": messages,
        "stream": False,
        "max_tokens": int(kw.get("max_tokens") or 1024),
    }, timeout)
    usage = data.get("usage") or {}
    USAGE["calls"] = int(USAGE.get("calls", 0)) + 1
    tokens = int(usage.get("completion_tokens") or 0)
    USAGE["tokens"] = int(USAGE.get("tokens", 0)) + tokens
    elapsed = max(0.001, time.time() - started)
    if tokens:
        LAST_TPS = round(tokens / elapsed, 2)
    return (data.get("choices") or [{}])[0].get("message", {}).get("content", "")


def _query_llm_with_tools(messages, tools=None, timeout: int = 600, **kw) -> dict:
    text = _query_llm(messages, timeout=timeout, **kw)
    return {"content": text, "tool_calls": []}
