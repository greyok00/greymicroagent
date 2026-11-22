from __future__ import annotations

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _Timeout
from typing import Any, Callable, Dict, List, Optional

TOOLS: Dict[str, Dict[str, Any]] = {}

_CMD_TIMEOUT = 3600
_CMD_MAX_OUT = 32000


def _schema(description: str, properties: Dict[str, Any],
            required: Optional[List[str]] = None) -> Dict[str, Any]:
    return {"description": description, "parameters": {
        "type": "object", "properties": properties,
        "required": required or []}}


def register_tool(name: str, schema: Dict[str, Any], handler: Callable,
                  category: str = "tool", **_extra) -> None:
    TOOLS[name] = {"schema": schema, "handler": handler, "category": category}


def list_tools(limit: Optional[int] = None, stub: bool = False) -> List[Dict[str, Any]]:
    names = list(TOOLS)
    if limit:
        names = names[:limit]
    out = []
    for n in names:
        s = TOOLS[n]["schema"]
        if stub:
            out.append({"name": n, "description": s.get("description", "")})
        else:
            out.append({"name": n, **s})
    return out


def get_schema(name: str) -> Optional[Dict[str, Any]]:
    t = TOOLS.get(name)
    return dict(t["schema"]) if t else None


def check_trust(result: Dict[str, Any]) -> str:
    blob = str(result.get("output", "")) + str(result.get("error", ""))
    for marker in ("ignore previous", "disregard all", "reveal your",
                   "send your prompt", "exfiltrate"):
        if marker in blob.lower():
            return "suspicious"
    return "ok"


def _resolve(name: str, args: Dict[str, Any]):
    if name in TOOLS:
        return name, args
    action = str(args.get("action") or "").strip()
    if action and (name + "_" + action) in TOOLS:
        rest = {k: v for k, v in args.items() if k != "action"}
        return name + "_" + action, rest
    return None, None


def execute_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    tname, targs = _resolve(name, args or {})
    if not tname:
        return {"ok": False, "output": "",
                "error": "unknown tool: " + name}
    schema = TOOLS[tname]["schema"]
    missing = [k for k in (schema.get("parameters", {}) or {}).get("required", [])
               if k not in (targs or {})]
    if missing:
        params = sorted((schema.get("parameters", {}) or {}).get("properties", {}).keys())
        return {"ok": False, "output": "",
                "error": "missing argument(s): %s — parameter names for %s are: %s" % (
                    ", ".join(missing), name, ", ".join(params) or "(none)")}
    try:
        result = TOOLS[tname]["handler"](**(targs or {}))
        if not isinstance(result, dict):
            result = {"ok": True, "output": str(result), "error": ""}
        result["trust"] = check_trust(result)
        return result
    except Exception as e:
        return {"ok": False, "output": "", "error": "%s: %s" % (name, e)}


def _run_command(command: str, timeout: int = 3600) -> Dict[str, Any]:
    try:
        shell = os.environ.get("COMSPEC") if os.name == "nt" else "/bin/bash"
        proc = subprocess.Popen(
            command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, executable=shell)
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except _Timeout:
            proc.kill()
            return {"ok": False, "output": "",
                    "error": "command timed out after %ds" % timeout}
        return {"ok": proc.returncode == 0, "output": (stdout or "")[-_CMD_MAX_OUT:],
                "error": (stderr or "")[-4000:], "code": proc.returncode}
    except Exception as e:
        return {"ok": False, "output": "", "error": str(e)}


def _executor_tool(name: str, args: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        fut = ex.submit(execute_tool, name, args)
        try:
            return fut.result(timeout=timeout)
        except _Timeout:
            return {"ok": False, "output": "",
                    "error": "tool %s timed out after %ds" % (name, timeout)}
    finally:
        ex.shutdown(wait=False)


def register_base(name: str, schema: Dict[str, Any], handler: Callable) -> None:
    register_tool(name, schema, handler)
