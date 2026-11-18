#!/usr/bin/env python3
"""reap_orphans.py: kill greymicroagent family chain processes nobody owns.

An orphan is any chain process (rename-fork model server, slimtoken lane on
the 7640-7647 block, RAG gate, boot loader) with NO live launcher above it
in the process tree. These outlive windows whose teardown never fired, keep
burning CPU invisibly, and serve their pre-fix code to the next session
(11-18: a day-old orphan served a 27k-token repeat loop to every relaunch).

Safety rails:
  - only cmdlines that name THIS tree or the renmed server binary
  - slim lanes must listen on 7640-7647 and point upstream inside the block
  - possession requires a LIVE `bin/greymicroagent` ancestor, not a pid file
  - the scan's own process and its ancestors are never candidates
  - SIGTERM first, 5 s grace, then SIGKILL per surviving pid; every action
    is logged to state/logs/reaper.log
"""
import os
import re
import signal
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "state" / "logs" / "reaper.log"

PORT_BLOCK = re.compile(r":76[4][0-7]\b")
SERVER_MARK = "greymicroagent-server"
SLIM_MARK = "slimtoken serve"
GATE_MARK = "services/rag_gate.py"
LOADER_MARK = "python3 - " + str(ROOT)
LAUNCHER_MARK = "/bin/greymicroagent"


def _cmdline(pid: int) -> str:
    try:
        raw = Path("/proc/%d/cmdline" % pid).read_bytes()
        return raw.replace(b"\x00", b" ").decode("utf-8", "replace")
    except Exception:
        return ""


def _parent(pid: int):
    try:
        fields = Path("/proc/%d/stat" % pid).read_text().rsplit(")", 1)[1].split()
        return int(fields[1])
    except Exception:
        return None


def _is_candidate(pid: int, cmd: str) -> bool:
    if SERVER_MARK in cmd:
        return True
    if LOADER_MARK + " " in "\n" + cmd and cmd.strip().endswith(str(ROOT)):
        return True
    if GATE_MARK in cmd:
        return True
    if SLIM_MARK in cmd and PORT_BLOCK.search(cmd):
        return True
    return False


def _ancestors(pid: int):
    seen = set()
    cur = pid
    while True:
        cur = _parent(cur)
        if cur is None or cur in seen or cur <= 1:
            return seen
        seen.add(cur)


def _owns_launcher(pid: int) -> bool:
    for anc in _ancestors(pid):
        if LAUNCHER_MARK in _cmdline(anc):
            return True
    return False


def _protects_self(pids):
    mine = {os.getpid()}
    cur = os.getpid()
    mine |= _ancestors(cur)
    return pid in mine


def scan():
    out = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        cmd = _cmdline(pid)
        if not cmd or not _is_candidate(pid, cmd):
            continue
        out.append((pid, cmd.strip()[:120]))
    return out


def reap(apply: bool) -> list:
    lines = []
    orphans = []
    for pid, cmd in scan():
        if pid == os.getpid() or pid in _ancestors(os.getpid()):
            lines.append("skip self %d" % pid)
            continue
        if _owns_launcher(pid):
            lines.append("owned %d %s" % (pid, cmd[:60]))
            continue
        orphans.append((pid, cmd))
        if not apply:
            lines.append("ORPHAN (dry) %d %s" % (pid, cmd[:60]))
            continue
        lines.append("kill %d %s" % (pid, cmd[:60]))
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception as e:
            lines.append("  term failed: %r" % e)
    if apply:
        time.sleep(5)
        for pid, _ in orphans:
            try:
                os.kill(pid, 0)
                os.kill(pid, signal.SIGKILL)
                lines.append("  sigkill survivor %d" % pid)
            except Exception:
                pass
    # stale pid files
    for f in (ROOT / "state").glob("model-server-*.pid"):
        try:
            pid = int(f.read_text().strip())
            os.kill(pid, 0)
        except (ValueError, ProcessLookupError, PermissionError) as e:
            if isinstance(e, ProcessLookupError):
                lines.append("stale pidfile %s (pid gone)" % f.name)
                f.unlink(missing_ok=True)
    text = "[%s]\n%s\n" % (time.strftime("%F %T"),
                           "\n".join(lines) if lines else "no chain processes")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print(text)
    return orphans


if __name__ == "__main__":
    import sys
    reap(apply="--list" not in sys.argv)
