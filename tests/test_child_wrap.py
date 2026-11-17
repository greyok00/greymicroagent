import os
import select
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRAP = ROOT / "services" / "child_wrap.py"
SLEEPER = "import time,os;print(os.getpid(),flush=True);time.sleep(30)"
DEADLINE_S = 3.0
TRACKED = []


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except (FileNotFoundError, ProcessLookupError, IndexError, ValueError):
        return False


def _track(proc_or_pid):
    pid = proc_or_pid if isinstance(proc_or_pid, int) else proc_or_pid.pid
    TRACKED.append(pid)
    return pid


def _reap_all():
    for pid in TRACKED:
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and any(_alive(p) for p in TRACKED):
        time.sleep(0.02)


def _spawn_wrap_bash(child_cmd):
    bash = subprocess.Popen(["bash", "-c", f'python3 "{WRAP}" {child_cmd}'],
                            stdout=subprocess.PIPE)
    _track(bash)
    return bash


def _read_child_pid(handle, timeout=15.0):
    ready, _, _ = select.select([handle.stdout], [], [], timeout)
    line = handle.stdout.readline() if ready else ""
    assert line, "child never printed its pid (wrapper missing or exec failed)"
    return _track(int(line.split()[0]))


def test_wrapper_execs_and_passes_through_output_and_exit_code():
    bash = _spawn_wrap_bash('python3 -c "print(7*6)"; echo rc=$?')
    try:
        out = bash.stdout.read().decode()
        bash.wait(timeout=10)
        assert out == "42\nrc=0\n"
    finally:
        _reap_all()
        assert not any(_alive(p) for p in TRACKED)


def test_wrapper_usage_without_argv_exits_2():
    r = subprocess.run(sys.executable + " " + str(WRAP), shell=True,
                       capture_output=True, text=True, timeout=10)
    try:
        assert r.returncode == 2
        assert "usage" in r.stderr
    finally:
        _reap_all()
        assert not any(_alive(p) for p in TRACKED)


def test_sigkilled_launcher_child_dies_within_3s():
    bash = _spawn_wrap_bash(f'python3 -c "{SLEEPER}" & wait')
    try:
        pid = _read_child_pid(bash)
        assert pid != bash.pid
        bash.send_signal(signal.SIGKILL)
        bash.wait(timeout=10)
        deadline = time.monotonic() + DEADLINE_S
        while time.monotonic() < deadline and _alive(pid):
            time.sleep(0.02)
        assert not _alive(pid), f"orphaned child {pid} survived launcher SIGKILL"
    finally:
        _reap_all()
        assert not any(_alive(p) for p in TRACKED), \
            f"survivors: {[p for p in TRACKED if _alive(p)]}"
