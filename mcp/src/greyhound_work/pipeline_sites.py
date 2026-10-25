import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
_REPO_ROOT = Path(__file__).resolve().parent
SITES = json.loads((_REPO_ROOT / 'research' / 'data' / 'sites.json').read_text())
EXCLUDED = set(SITES.get('excluded', []))
TASK_RE = re.compile('\\b(?:task[-_ ]?)?([1-4])\\b')

def task_key(task_id) -> str:
    if task_id is not None and str(task_id).strip() != '':
        m = TASK_RE.search(str(task_id))
        if m:
            return f'task-{m.group(1)}'
    return ''

def _now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
_TASK_REG_PATH = os.path.join(_REPO_ROOT, 'research', 'task-registry.json')

def _session_id() -> str:
    return os.environ.get('GREYHOUND_SESSION_ID') or 'unknown-session'

def task_registry(assign: str | None=None, task_id=None) -> dict:
    reg: dict = {}
    try:
        with open(_TASK_REG_PATH) as f:
            reg = json.load(f)
    except Exception:
        reg = {}
    if assign:
        tk = task_key(assign)
        if not tk:
            raise ValueError(f'unknown task slot: {assign!r} (task-1..task-4)')
        import socket
        prev = reg.get(tk) or {}
        prev_owner = prev.get('owner_session', '')
        sid = _session_id()
        reg[tk] = {'owner_session': sid, 'assigned_at': _now(), 'pid': os.getpid(), 'host': socket.gethostname(), 'pages_dir': os.environ.get('RESEARCH_PAGES', '')}
        try:
            os.makedirs(_TASK_REG_PATH.replace('/task-registry.json', ''), exist_ok=True)
            with open(_TASK_REG_PATH, 'w') as f:
                json.dump(reg, f, indent=1)
        except Exception:
            pass
        out_reg = dict(reg)
        out_reg['_last_assignment'] = {'slot': tk, 'owner_session': sid, 'reassigned_from': prev_owner, 'note': 'slot was previously held by ' + prev_owner if prev_owner and prev_owner != sid else 'fresh claim'}
        return out_reg
    return reg