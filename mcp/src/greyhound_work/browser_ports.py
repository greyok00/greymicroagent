import json
import os
import re
import signal
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence
CANDIDATE_MAPS = (str(Path(__file__).resolve().parent / 'research' / 'browser-ports.json'),)

def _find_chrome() -> str:
    import glob
    cands = sorted(glob.glob(os.path.expanduser('~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome')), reverse=True)
    cands += ['/usr/bin/chromium', '/usr/bin/chromium-browser', '/usr/bin/google-chrome-stable']
    return next((c for c in cands if os.path.exists(c)), '/usr/bin/chromium')
CHROME_BIN = _find_chrome()

def load_map() -> Dict[str, Any]:
    for p in CANDIDATE_MAPS:
        try:
            with open(p) as f:
                return json.load(f)
        except Exception:
            continue
    raise RuntimeError('browser-ports.json not found in any known location')

def _norm(s: str) -> str:
    return re.sub('[^a-z0-9]+', '-', str(s).lower()).strip('-')

def resolve(task: str='', pages_env: str='') -> Dict[str, Any]:
    m = load_map()

    def _match(name_value: str):
        n = _norm(name_value)
        if not n:
            return None
        for key, cfg in m.get('tasks', {}).items():
            for alias in [key] + cfg.get('aliases', []):
                if n == _norm(alias):
                    cfg2 = dict(cfg)
                    if 'profile' in cfg2:
                        cfg2['profile'] = os.path.expanduser(str(cfg2['profile']))
                    cfg2['key'], cfg2['name'] = (key, alias)
                    return cfg2
        if pages_env and name_value == pages_env:
            return None
        for key, cfg in m.get('tasks', {}).items():
            for alias in [key] + cfg.get('aliases', []):
                a = _norm(alias)
                if a and a in n:
                    cfg2 = dict(cfg)
                    cfg2['key'], cfg2['name'] = (key, alias)
                    return cfg2
        return None
    for stage in ({'task': task, 'ok_if': bool(task)}, {'task': os.environ.get('RESEARCH_TASK', ''), 'ok_if': True}, {'task': pages_env, 'ok_if': bool(pages_env)}):
        if not stage['ok_if']:
            continue
        cfg2 = _match(stage['task'])
        if cfg2:
            return cfg2
    raise RuntimeError("no task identified for this fetch — set RESEARCH_TASK (task-1|task-2|task-3|task-4) or pass the task's pages dir; refusing to guess a port")

def task_cfg(task: str='', pages_env: str='') -> Dict[str, Any]:
    return resolve(task=task, pages_env=pages_env)
ORPHAN_MIN_AGE_S = 2.0

def _ps_snapshot() -> List[Dict[str, Any]]:
    r = subprocess.run(['ps', '-eo', 'pid=,comm=,etimes=,args='], capture_output=True, text=True, timeout=10)
    procs: List[Dict[str, Any]] = []
    for line in (r.stdout or '').splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        try:
            etimes = float(parts[2])
        except (ValueError, IndexError):
            etimes = None
        procs.append({'pid': pid, 'comm': parts[1], 'etimes': etimes, 'args': parts[3] if len(parts) > 3 else ''})
    return procs

def _xvfb_pids(n: int, snapshot: Sequence[Dict[str, Any]]) -> List[int]:
    pat = re.compile(f'(?:^|\\s):{int(n)}(?:\\s|$)')
    pids: List[int] = []
    for proc in snapshot or []:
        if os.path.basename(str(proc.get('comm') or '')) != 'Xvfb':
            continue
        age = proc.get('etimes')
        if age is not None:
            try:
                if float(age) < ORPHAN_MIN_AGE_S:
                    continue
            except (TypeError, ValueError):
                pass
        if pat.search(str(proc.get('args') or '')):
            pids.append(int(proc['pid']))
    return pids

def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False

def inspect_display(n: int, *, ps_snapshot: Optional[List[Dict[str, Any]]]=None, socket_path: Optional[str]=None, lock_path: Optional[str]=None) -> Dict[str, Any]:
    display = int(n)
    sock = socket_path if socket_path is not None else f'/tmp/.X11-unix/X{display}'
    lock = lock_path if lock_path is not None else f'/tmp/.X{display}-lock'
    snap = ps_snapshot if ps_snapshot is not None else _ps_snapshot()
    pids = _xvfb_pids(display, snap)
    has_socket = os.path.exists(sock)
    has_lock = os.path.exists(lock)
    return {'display': display, 'pids': pids, 'socket': has_socket, 'lock': has_lock, 'socket_path': sock, 'lock_path': lock, 'orphan': bool(pids) and (not (has_socket or has_lock))}

def reap_orphan_display(n: int, *, ps_snapshot: Optional[List[Dict[str, Any]]]=None, socket_path: Optional[str]=None, lock_path: Optional[str]=None, kill: Optional[Callable[[int, int], Any]]=None, alive: Optional[Callable[[int], bool]]=None, wait_s: float=1.5) -> Dict[str, Any]:
    display = int(n)
    info = inspect_display(display, ps_snapshot=ps_snapshot, socket_path=socket_path, lock_path=lock_path)
    result: Dict[str, Any] = {**info, 'reclaimed': False, 'killed': []}
    if display == 0:
        result['reason'] = 'display :0 is never touched'
        return result
    if info['socket'] or info['lock']:
        result['reason'] = 'live socket/lock present — not an orphan'
        return result
    if not info['pids']:
        result['reason'] = 'no Xvfb process on this display'
        return result
    _kill = kill or os.kill
    _alive = alive or _pid_alive
    killed: List[int] = []
    for pid in info['pids']:
        try:
            _kill(pid, signal.SIGTERM)
            killed.append(pid)
        except Exception as exc:
            result.setdefault('errors', []).append(f'pid {pid}: {exc}')
    deadline = time.time() + max(0.0, wait_s)
    while killed and time.time() < deadline:
        if not any((_alive(pid) for pid in killed)):
            break
        time.sleep(0.1)
    for pid in killed:
        if _alive(pid):
            try:
                _kill(pid, signal.SIGKILL)
            except Exception:
                pass
    result['killed'] = killed
    result['reclaimed'] = bool(killed)
    result['reason'] = 'orphan Xvfb reclaimed (no socket/lock)' if killed else 'orphan Xvfb found but termination failed'
    return result

def _note(path: str, msg: str) -> None:
    if not path:
        return
    try:
        import datetime
        with open(path, 'a') as f:
            f.write(f"{datetime.datetime.now().isoformat(timespec='seconds')} {msg}\n")
    except Exception:
        pass

def cdp_http(cfg: Dict[str, Any]) -> str:
    return f"http://127.0.0.1:{cfg['port']}"

def _healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/version', timeout=3):
            return True
    except Exception:
        return False

def launch_cmd(cfg: Dict[str, Any]) -> List[str]:
    launcher = str(Path(__file__).with_name('patchright_headless.py'))
    return ['setsid', 'nohup', 'python3', launcher, '--port', str(cfg['port']), '--profile', str(cfg['profile'])]

def ensure(cfg: Dict[str, Any], wait_s: int=40, note: str='') -> bool:
    port = int(cfg['port'])
    if _healthy(port):
        return True
    env = {'HOME': os.environ.get('HOME', '/home/grey'), 'PATH': '/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8'}
    try:
        subprocess.Popen(launch_cmd(cfg), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except Exception:
        return False
    deadline = time.time() + wait_s
    while time.time() < deadline:
        if _healthy(port):
            if note:
                try:
                    with open(note, 'a') as f:
                        import datetime
                        f.write(f"{datetime.datetime.now().isoformat(timespec='seconds')} auto-launched task browser port={port} profile={cfg['profile']} (headless, no display)\n")
                except Exception:
                    pass
            return True
        time.sleep(1)
    return False

class TaskLock:

    def __init__(self, cfg: Dict[str, Any]):
        base = os.path.expanduser('~/.cache/greyhound')
        self.path = os.path.join(base, 'locks', f"{cfg['key']}.lock")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.fh = None

    def acquire(self, wait_s: float=90.0) -> bool:
        import fcntl
        self.fh = open(self.path, 'w')
        end = time.time() + wait_s
        while time.time() < end:
            try:
                fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except OSError:
                time.sleep(2)
        self.fh.close()
        self.fh = None
        return False

    def release(self):
        import fcntl
        if self.fh:
            try:
                fcntl.flock(self.fh, fcntl.LOCK_UN)
                self.fh.close()
            except Exception:
                pass
            self.fh = None