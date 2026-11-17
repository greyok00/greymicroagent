"""Greypentest exec gate — fail-closed, argv-only, no shell.

Policy (from ../policy.json, never overridable at runtime):
  mode ∈ {"closed", "allowlist"}; anything else = closed. A policy error
  (missing file, bad JSON, unreadable) DENIES — never widens. Commands run as
  argv lists via subprocess (no shell string exists anywhere), inside the
  Greypentest workspace, with hard timeout + output caps. Deny-listed first
  tokens (destructors, network escapes) are rejected even if allowlisted.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path


def _resolve_root() -> Path:
    # Adaptive root: nearest ancestor that actually ships policy.json.
    # Source layout:  greypentest/greypentest/brain/<mod>.py -> ROOT (2 up)
    # Compiled:      <root>/mcp/<mod>.so         -> <root>/mcp/ (1 up)
    # Walk up from this file and take the first dir with policy.json.
    here = Path(__file__).resolve().parent
    for d in (here, *here.parents):
        if (d / "policy.json").exists():
            return d
    return here.parent  # fallback to legacy 2-up


ROOT = _resolve_root()
POLICY = ROOT / "policy.json"

# First tokens that may never run, regardless of allowlist content.
NEVER = {"rm", "chmod", "chown", "mkfs", "dd", "sudo", "su", "nc", "ncat",
         "curl", "wget", "ssh", "scp", "mount", "umount", "insmod",
         "modprobe", "bash", "sh", "zsh", "perl", "python", "python3",
         "powershell", "nvidia-smi", "apt", "apt-get", "pip", "pip3",
         "docker", "systemctl", "service", "kill", "pkill", "shutdown"}

_MAX_OUTPUT = 2_000_000      # bytes
_DEFAULT_TIMEOUT = 900        # s; policy may only LOWER this, never raise

# 2026-10-30 greypentest (owner: "must be installed tools, checks and
# downloads tools needed"): the suite ships no binaries, so the allowlist is
# bare tool NAMES resolved at gate time against TRUSTED install dirs — a
# direct isfile/X_OK probe, deliberately NOT a $PATH walk, so nothing on
# PATH (relative, writable dirs) can impersonate a tool.
# Order matters: distro-shipped LOOKALIKES (e.g. Debian's C++ httpx at
# /usr/bin/httpx) must not shadow the real go-installed scanner in ~/go/bin —
# trusted dirs are probed in this exact order.
_TRUSTED_DIRS = [
    str(ROOT / "bin"),                    # legacy suite copies (may be absent)
    "/usr/local/bin", os.path.expanduser("~/go/bin"), "/usr/bin",
    os.path.expanduser("~/.local/bin"),
    "/usr/sbin", "/usr/local/sbin",
]


def resolve_tool(name: str) -> str | None:
    """Bare tool name → absolute path in a trusted dir (or None)."""
    if os.sep in name:
        return None                       # absolute/relative goes via allowlist
    for d in _TRUSTED_DIRS:
        cand = os.path.join(d, name)
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None
    # 2026-10-31 QA (GT-01): the shutil.which() PATH fallback is gone — a
    # writeable PATH dir could still impersonate an allowlisted tool.


class GateDeny(Exception):
    """A hard, user-visible refusal."""


def _policy() -> dict:
    try:
        data = json.loads(POLICY.read_text())
    except Exception as e:                       # fail-CLOSED on any error
        raise GateDeny(f"policy unreadable → deny ({type(e).__name__}: {e})")
    mode = data.get("execution_mode")
    if mode not in ("closed", "allowlist"):
        raise GateDeny("policy execution_mode must be closed|allowlist")
    return data


def tokenize(command: str) -> list:
    """Shell-free argv tokenization. Metachars are a hard deny (never a
    reinterpretation chance)."""
    try:
        argv = shlex.split(command)
    except ValueError as e:
        raise GateDeny(f"unparseable argv → deny ({e})")
    if not argv:
        raise GateDeny("empty command")
    if any(ch in command for ch in ";|&`$<>(){}\n") :
        raise GateDeny("shell metacharacters are not accepted — pass plain argv")
    return argv


def check(argv: list, *, timeout: int | None = None) -> dict:
    """Gate a tokenized command. Returns {allowed, reason, timeout} or raises
    GateDeny. Timeouts may only be tightened by the caller."""
    pol = _policy()
    if pol["mode"] == "closed":
        raise GateDeny("execution_mode=closed — human approval required, none wired")
    # HARD DENY: policy.deny names are unrunnable even if re-added to the
    # allowlist later (2026-10-30: "holehe" blocked owner-side).
    denied = set(pol.get("deny", []))
    head0 = Path(argv[0]).name
    if argv[0] in denied or head0 in denied:
        raise GateDeny(f"'{argv[0]}' is on the policy DENY list — never runnable")
    raw = pol.get("allowlist", [])
    # Allowlist: bare tool NAMES (resolved against trusted dirs at gate time)
    # plus legacy forms — "$ROOT/<path>" resolves against ROOT, real paths
    # pass through. A bare name on the list is allowed only when resolve_tool
    # finds it in a trusted dir; the command then runs AS that absolute path.
    allow_names: set[str] = set()
    allow_paths: set[str] = set()
    for e in raw:
        if e.startswith("$ROOT/"):
            allow_paths.add(str(ROOT / e[6:]))
        elif "/" in e:
            allow_paths.add(os.path.expanduser(e))
        else:
            allow_names.add(e)
    head = Path(argv[0]).name                    # bare name (no path tricks)
    if os.sep not in argv[0]:
        # bare name: must be allowlisted by name AND resolvable in a trusted
        # dir; the command then runs AS the resolved absolute path.
        if argv[0] not in allow_names:
            raise GateDeny(
                f"'{argv[0]}' is not on the runtime allowlist — policy.json "
                "lists the tools by name; add it there first")
        resolved = resolve_tool(argv[0])
        if not resolved:
            raise GateDeny(
                f"'{argv[0]}' is allowlisted but NOT installed on this box — "
                "call tool_check/tool_install to get it")
        argv = [resolved] + list(argv[1:])       # run the trusted absolute path
    elif argv[0] not in allow_paths:
        raise GateDeny(
            f"'{argv[0]}' is not on the runtime allowlist — exactly the "
            "absolute path listed in policy.json may run")
    if str(argv[0]).startswith("-") or ".." in argv:
        raise GateDeny("illegal argv shape")
    if head in NEVER:
        raise GateDeny(f"'{head}' is never executable through the gate")
    # Timeout cap: policy may set exec_timeout_cap (s) to raise the ceiling for
    # lab/remote runs; absent, the fail-closed default is 60s. The caller's
    # timeout is clamped to the cap (never above it).
    cap = pol.get("exec_timeout_cap", _DEFAULT_TIMEOUT)
    t = min(timeout or _DEFAULT_TIMEOUT, cap)
    return {"allowed": True, "reason": f"allowlisted:{head}", "timeout": t,
            "max_output": _MAX_OUTPUT, "resolved": argv[0] if os.sep in argv[0] else None}


def run(argv_or_command, *, cwd: str | None = None, timeout: int | None = None,
        stdin_text: str | None = None, dry_check: bool = False) -> dict:
    """Check, then run argv (never a shell). stdin_text is piped raw (the
    python sandbox uses it; input never passes through an interpreter that
    could reinterpret metacharacters)."""
    if isinstance(argv_or_command, str):
        argv = tokenize(argv_or_command)
    else:
        argv = list(argv_or_command)
    gate = check(argv, timeout=timeout)   # check() may REPLACE argv[0] with
    if gate.get("resolved") and argv[0] != gate["resolved"]:
        argv = [gate["resolved"]] + list(argv[1:])   # the trusted absolute path
    if dry_check:
        return {"ok": True, "gate": gate, "ran": False}
    workspace = ROOT / "workspace"               # commands always cd here
    workspace.mkdir(parents=True, exist_ok=True)
    try:
        p = subprocess.run(
            argv, cwd=cwd or str(workspace),
            input=stdin_text, capture_output=True, text=True,
            timeout=gate["timeout"])
        out, err, rc = p.stdout, p.stderr, p.returncode
    except FileNotFoundError:
        return {"ok": False, "output": "", "stdout": "", "stderr": "",
                "error": f"binary not found: {argv[0]}", "returncode": 127}
    except subprocess.TimeoutExpired as e:
        # Preserve PARTIAL output: scanners (nikto/dirb/ffuf) print findings
        # incrementally, so a hard-kill mid-run still has real evidence. The
        # gate used to throw it away (0B), which looked like a silent no-op.
        po = e.stdout if isinstance(e.stdout, bytes) else \
            (e.stdout or "").encode()
        pe = e.stderr if isinstance(e.stderr, bytes) else \
            (e.stderr or "").encode()
        po = po.decode(errors="replace")[:gate["max_output"]]
        pe = pe.decode(errors="replace")[:gate["max_output"]]
        return {"ok": False, "stdout": po, "stderr": pe,
                "output": (po + ("\n" + pe if pe else "")),
                "error": f"timed out after {gate['timeout']}s (hard kill, "
                         f"partial output preserved)", "returncode": -9}
    out, err = out[:gate["max_output"]], err[:gate["max_output"]]
    if rc != 0:
        return {"ok": False, "stdout": out, "stderr": err, "output": err or out,
                "error": f"exit {rc}", "returncode": rc}
    return {"ok": True, "stdout": out, "stderr": err, "output": out,
            "returncode": rc, "error": ""}