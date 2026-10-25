from __future__ import annotations
import json
import shlex
import subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
POLICY = ROOT / 'policy.json'
NEVER = {'rm', 'chmod', 'chown', 'mkfs', 'dd', 'sudo', 'su', 'nc', 'ncat', 'curl', 'wget', 'ssh', 'scp', 'mount', 'umount', 'insmod', 'modprobe', 'bash', 'sh', 'zsh', 'perl', 'python', 'python3', 'powershell', 'nvidia-smi', 'apt', 'apt-get', 'pip', 'pip3', 'docker', 'systemctl', 'service', 'kill', 'pkill', 'shutdown'}
_MAX_OUTPUT = 2000000
_DEFAULT_TIMEOUT = 60

class GateDeny(Exception):
    pass

def _policy() -> dict:
    try:
        data = json.loads(POLICY.read_text())
    except Exception as e:
        raise GateDeny(f'policy unreadable → deny ({type(e).__name__}: {e})')
    mode = data.get('execution_mode')
    if mode not in ('closed', 'allowlist'):
        raise GateDeny('policy execution_mode must be closed|allowlist')
    return data

def tokenize(command: str) -> list:
    try:
        argv = shlex.split(command)
    except ValueError as e:
        raise GateDeny(f'unparseable argv → deny ({e})')
    if not argv:
        raise GateDeny('empty command')
    if any((ch in command for ch in ';|&`$<>(){}\n')):
        raise GateDeny('shell metacharacters are not accepted — pass plain argv')
    return argv

def check(argv: list, *, timeout: int | None=None) -> dict:
    pol = _policy()
    if pol['mode'] == 'closed':
        raise GateDeny('execution_mode=closed — human approval required, none wired')
    allow = pol.get('allowlist', [])
    head = Path(argv[0]).name
    if argv[0] not in allow:
        raise GateDeny(f"'{argv[0]}' is not on the runtime allowlist — exactly the absolute path listed in policy.json may run (bare names are rejected so a PATH-local impersonator can't slip in)")
    if str(argv[0]).startswith('-') or '..' in argv:
        raise GateDeny('illegal argv shape')
    if head in NEVER:
        raise GateDeny(f"'{head}' is never executable through the gate")
    t = min(timeout or _DEFAULT_TIMEOUT, _DEFAULT_TIMEOUT)
    return {'allowed': True, 'reason': f'allowlisted:{head}', 'timeout': t, 'max_output': _MAX_OUTPUT}

def run(argv_or_command, *, cwd: str | None=None, timeout: int | None=None, stdin_text: str | None=None, dry_check: bool=False) -> dict:
    if isinstance(argv_or_command, str):
        argv = tokenize(argv_or_command)
    else:
        argv = list(argv_or_command)
    gate = check(argv, timeout=timeout)
    if dry_check:
        return {'ok': True, 'gate': gate, 'ran': False}
    workspace = ROOT / 'workspace'
    workspace.mkdir(parents=True, exist_ok=True)
    try:
        p = subprocess.run(argv, cwd=cwd or str(workspace), input=stdin_text, capture_output=True, text=True, timeout=gate['timeout'])
        out, err, rc = (p.stdout, p.stderr, p.returncode)
    except FileNotFoundError:
        return {'ok': False, 'output': '', 'stdout': '', 'stderr': '', 'error': f'binary not found: {argv[0]}', 'returncode': 127}
    except subprocess.TimeoutExpired:
        return {'ok': False, 'output': '', 'stdout': '', 'stderr': '', 'error': f"timed out after {gate['timeout']}s (hard kill)", 'returncode': -9}
    out, err = (out[:gate['max_output']], err[:gate['max_output']])
    if rc != 0:
        return {'ok': False, 'stdout': out, 'stderr': err, 'output': err or out, 'error': f'exit {rc}', 'returncode': rc}
    return {'ok': True, 'stdout': out, 'stderr': err, 'output': out, 'returncode': rc, 'error': ''}