#!/usr/bin/env python3
"""Close zombie/hung listeners on ports this product owns.

Ports in scope:
  product  7640-7647  (model, gate, slimtoken)
  slots    9351-9354  (greysearch slot browsers)
  searx    8888       (local SearXNG)

A listener is closed only when it is demonstrably not serving:
  - process state Z (zombie), or
  - its health probe hangs past the timeout while the TCP port accepts.
Healthy listeners and listeners we just launched are left alone. A hung
foreign listener on an owned port is closed, but nothing foreign is
relaunched. A hung slot browser is killed and `browser_session.ensure_daemon`
launches a fresh one. A hung SearXNG is restarted with its own command line
only when it is not supervised (systemd will own it otherwise).

Usage: reap_hung_ports.py [--product] [--slots] [--searx] [--all] [--apply] [--keep PID,...]
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRODUCT_PORTS = list(range(7640, 7648))
SLOT_PORTS = [9351, 9352, 9353, 9354]
SEARX_PORT = 8888
PRODUCT_MARKERS = ("greymicroagent-server", "slimtoken", "rag_gate.py")
BROWSER_MARKERS = ("chrome", "task-", "greysearch")
SEARX_MARKERS = ("searx.webapp", "searxng-plain")


VERBOSE = False


def log(msg: str) -> None:
    print("%s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg), flush=True)


def log_v(msg: str) -> None:
    if VERBOSE:
        log(msg)


def listener_pid(port: int):
    try:
        out = subprocess.run(
            ["ss", "-ltnp"], capture_output=True, text=True, timeout=5
        ).stdout
    except Exception:
        return None
    for line in out.splitlines():
        if re.search(r":%d\s" % port, line):
            match = re.search(r"pid=(\d+)", line)
            if match:
                return int(match.group(1))
    return None


def pid_cmdline(pid: int) -> str:
    try:
        raw = Path("/proc/%d/cmdline" % pid).read_bytes()
        return raw.replace(b"\0", b" ").decode("utf-8", "ignore").strip()
    except OSError:
        return ""


def pid_state(pid: int) -> str:
    try:
        raw = Path("/proc/%d/stat" % pid).read_text(errors="ignore")
        return raw.rsplit(")", 1)[1].split()[0]
    except OSError:
        return ""


def http_ok(port: int, path: str, timeout: float) -> bool:
    try:
        p = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "--max-time", str(timeout),
             "http://127.0.0.1:%d%s" % (port, path)],
            capture_output=True, timeout=timeout + 3,
        )
        # curl exits non-zero on an empty reply (52) or a reset connection
        # (56) - a listener that accepts TCP then dies per-connection is not
        # healthy and must be reaped, not skipped.
        return p.returncode == 0
    except Exception:
        return False


def cdp_healthy(port: int, timeout: float = 12.0) -> bool:
    try:
        import importlib.util

        if importlib.util.find_spec("patchright") is None:
            return http_ok(port, "/json/version", 3)
    except Exception:
        return http_ok(port, "/json/version", 3)
    script = (
        "from patchright.sync_api import sync_playwright\n"
        "p=sync_playwright().start()\n"
        "b=p.chromium.connect_over_cdp('http://127.0.0.1:%d', timeout=%d)\n"
        "b.close(); p.stop()\n" % (port, int(timeout * 1000))
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=timeout + 10,
            env={**os.environ, "PYTHONPATH": str(ROOT)},
            cwd=str(ROOT),
        )
        return proc.returncode == 0
    except Exception:
        return False


def kill_pid(pid: int, label: str) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    for _ in range(10):
        if not Path("/proc/%d" % pid).exists():
            log("%s pid %d closed" % (label, pid))
            return
        time.sleep(0.5)
    try:
        os.kill(pid, signal.SIGKILL)
        log("%s pid %d killed" % (label, pid))
    except OSError:
        pass


def restart_searx(pid: int) -> None:
    cmdline = pid_cmdline(pid)
    if not any(marker in cmdline for marker in SEARX_MARKERS):
        log("searx: listener on %d is not ours; not relaunching" % SEARX_PORT)
        return
    try:
        argv = Path("/proc/%d/cmdline" % pid).read_bytes().split(b"\0")
        argv = [a.decode("utf-8", "ignore") for a in argv if a]
        cwd = os.readlink("/proc/%d/cwd" % pid)
        env = {}
        for item in Path("/proc/%d/environ" % pid).read_bytes().split(b"\0"):
            if b"=" in item:
                key, val = item.split(b"=", 1)
                env[key.decode("utf-8", "ignore")] = val.decode("utf-8", "ignore")
    except OSError:
        return
    time.sleep(1)
    if listener_pid(SEARX_PORT):
        log("searx: port already re-bound; no relaunch")
        return
    try:
        subprocess.Popen(
            argv, cwd=cwd, env=env, start_new_session=True,
            stdout=open("/tmp/searxng-plain.log", "ab"),
            stderr=subprocess.STDOUT,
        )
        log("searx: relaunched")
    except Exception as exc:
        log("searx: relaunch failed: %s" % exc)


def ensure_slot_browser() -> None:
    script = (
        "import sys; sys.path.insert(0, %r); "
        "from core.greysearch import browser_session as b; "
        "print(b.ensure_daemon(60))" % str(ROOT)
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True,
            timeout=90, cwd=str(ROOT),
        )
        log("slots: ensure_daemon rc=%d out=%s" % (proc.returncode, (proc.stdout or "").strip()[:60]))
    except Exception as exc:
        log("slots: ensure_daemon failed: %s" % exc)


def check_product(port: int, apply: bool, keep: set[int]) -> None:
    pid = listener_pid(port)
    if not pid:
        log_v("product:%d free" % port)
        return
    if pid in keep:
        log("product:%d pid %d is the process just launched; kept" % (port, pid))
        return
    cmd = pid_cmdline(pid)
    state = pid_state(pid)
    if state == "Z":
        log("product:%d pid %d zombie; closing" % (port, pid))
        if apply:
            kill_pid(pid, "product:%d" % port)
        return
    # The triple mixes roles: model and gate serve /health, slimtoken serves
    # /metrics. A hung listener fails both; a live one passes one.
    healthy = http_ok(port, "/health", 3) or http_ok(port, "/metrics", 3)
    if healthy:
        log_v("product:%d pid %d healthy" % (port, pid))
        return
    if not any(marker in cmd for marker in PRODUCT_MARKERS):
        log("product:%d pid %d foreign and unresponsive; %s" %
            (port, pid, "closing" if apply else "would close"))
        if apply:
            kill_pid(pid, "product:%d" % port)
        return
    log("product:%d pid %d hung (%s); %s" %
        (port, pid, cmd[:60], "closing" if apply else "would close"))
    if apply:
        kill_pid(pid, "product:%d" % port)


def check_slot(port: int, apply: bool, keep: set[int]) -> bool:
    pid = listener_pid(port)
    if not pid:
        log_v("slots:%d free" % port)
        return False
    if pid in keep:
        log("slots:%d pid %d is the process just launched; kept" % (port, pid))
        return False
    cmd = pid_cmdline(pid)
    state = pid_state(pid)
    if state == "Z":
        log("slots:%d pid %d zombie; closing" % (port, pid))
        if apply:
            kill_pid(pid, "slots:%d" % port)
        return True
    if cdp_healthy(port):
        log_v("slots:%d pid %d healthy" % (port, pid))
        return False
    log("slots:%d pid %d hung CDP (%s); %s" %
        (port, pid, cmd[:50], "closing" if apply else "would close"))
    if apply:
        kill_pid(pid, "slots:%d" % port)
    return True


def check_searx(apply: bool, keep: set[int]) -> None:
    pid = listener_pid(SEARX_PORT)
    if not pid:
        log_v("searx:%d free" % SEARX_PORT)
        return
    if pid in keep:
        return
    cmd = pid_cmdline(pid)
    if not any(marker in cmd for marker in SEARX_MARKERS):
        if not http_ok(SEARX_PORT, "/search?q=ping&format=json", 8):
            log("searx:%d foreign and unresponsive; %s" %
                (SEARX_PORT, "closing" if apply else "would close"))
            if apply:
                kill_pid(pid, "searx")
        return
    # SearXNG serves / but a wedged webapp hangs on /search.
    if http_ok(SEARX_PORT, "/search?q=ping&format=json", 8):
        log_v("searx:%d pid %d healthy" % (SEARX_PORT, pid))
        return
    log("searx:%d pid %d hung search endpoint; %s" %
        (SEARX_PORT, pid, "closing" if apply else "would close"))
    if apply:
        kill_pid(pid, "searx")
        restart_searx(pid)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--product", action="store_true")
    parser.add_argument("--slots", action="store_true")
    parser.add_argument("--searx", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--keep", default="")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    global VERBOSE
    VERBOSE = args.verbose
    keep = {int(x) for x in re.split(r"[,\s]+", args.keep) if x.isdigit()}
    do_product = args.product or args.all or not (args.slots or args.searx)
    do_slots = args.slots or args.all
    do_searx = args.searx or args.all
    if do_product:
        for port in PRODUCT_PORTS:
            check_product(port, args.apply, keep)
    if do_slots:
        closed = False
        for port in SLOT_PORTS:
            closed = check_slot(port, args.apply, keep) or closed
        if closed and args.apply:
            time.sleep(1)
            ensure_slot_browser()
    if do_searx:
        check_searx(args.apply, keep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
