from __future__ import annotations
import hashlib
import json


def _digest(name: str, args_dump: str) -> str:
    h = hashlib.sha1()
    h.update(name.encode())
    h.update(b"\x00")
    try:
        canon = json.dumps(json.loads(args_dump), sort_keys=True,
                           separators=(",", ":"))
    except Exception:
        canon = " ".join(args_dump.split())
    h.update(canon.encode())
    return h.hexdigest()[:12]


def repetition_tool_loop(window: list[dict], limit: int = 3):
    if not window or window[-1].get("kind") != "tool_call":
        return None
    calls = [r for r in window if r.get("kind") == "tool_call"]
    if len(calls) < limit:
        return None
    recent = calls[-limit:]
    digests = {r.get("digest") for r in recent}
    if len(digests) <= 1 and all(r.get("tool") == recent[0].get("tool")
                                 for r in recent):
        outs = {r.get("result_hash") for r in recent}
        detail = (f"{recent[0].get('tool')} issued {limit}x with identical "
                  f"args and {'identical' if len(outs) <= 1 else 'similar'} "
                  f"results")
        return ("F4", detail, "high")
    return None


def one_token_storm(window: list[dict], min_turns: int = 3):
    recent = [r for r in window if r.get("kind") == "model_turn"][-min_turns:]
    if len(recent) < min_turns:
        return None
    if all((r.get("tokens") or 0) < 2 for r in recent):
        return ("F2", f"{min_turns} consecutive ~empty model turns (storm)",
                "high")
    return None


def error_burst(window: list[dict], at_least: int = 4, in_window: int = 6):
    recent = [r for r in window if r.get("kind") == "tool_result"][-in_window:]
    if len(recent) < in_window:
        return None
    errs = [r for r in recent if r.get("error")]
    if len(errs) >= at_least:
        return ("F2", f"{len(errs)}/{in_window} recent tool results errored",
                "medium")
    return None


def refusal_repeat(window: list[dict], limit: int = 3):
    recent = [r for r in window if r.get("kind") == "refusal"][-limit:]
    if len(recent) < limit:
        return None
    families = {r.get("reason_family") for r in recent}
    if len(families) <= 1:
        fam = recent[0].get("reason_family", "gate")
        return ("F3", f"{limit}x same refusal family ({fam}) — model not "
                      f"acting on prose rule", "high")
    return None


def length_storm(window: list[dict], limit: int = 3):
    recent = [r for r in window if r.get("kind") == "stop_reason"][-limit:]
    if len(recent) < limit:
        return None
    if all(r.get("reason") == "length" for r in recent):
        return ("F2", "3 consecutive truncations (stopReason=length) — "
                      "context exhausted; compact or split the task", "high")
    return None


STRUCTURED_TOOLS = {"write", "edit", "subagent"}


def args_conform(name: str, args: dict) -> tuple[bool, str]:
    if name == "bash":
        cmd = args.get("command")
        if not isinstance(cmd, str) or not cmd.strip():
            return False, "bash tool call had no command text"
        if "\n" in cmd:
            return False, ("bash calls must be one single-line command; "
                           "multiline scripts belong in a written file")
    if name in ("write", "edit"):
        p = args.get("path") or args.get("file_path")
        if not isinstance(p, str) or not p.strip():
            return False, f"{name} tool call missing a file path"
    return True, ""
