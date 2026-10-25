from __future__ import annotations
import ast
import subprocess
import sys
ALLOWED_MODULES = set('\njson re sqlite3 datetime pathlib math decimal fractions statistics itertools\nfunctools collections hashlib base64 binascii struct zlib gzip csv io os.path\ntyping dataclasses textwrap uuid random secrets logging argparse\n'.split())

class SandboxDeny(Exception):
    pass

def _imports(code: str) -> set:
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise SandboxDeny(f"code doesn't parse → deny ({e})")
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name.split('.')[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                found.add(node.module.split('.')[0])
    return found

def check(code: str) -> dict:
    found = _imports(code)
    bad = found - ALLOWED_MODULES
    if bad:
        raise SandboxDeny('imports not on the allowlist → deny: ' + ', '.join(sorted(bad)))
    for token in ('eval(', 'exec(', 'compile(', '__import__', 'open('):
        if token in code:
            raise SandboxDeny(f"{token.rstrip('(')} is not allowed in sandbox")
    return {'allowed': True}
NO_NET_SITECUSTOMIZE = '\n'.join(['import socket', 'class _Refused:', '    def __getattr__(self, n):', "        raise RuntimeError('network disabled in python sandbox')", 'socket.socket = _Refused', "socket.create_connection = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('network disabled'))"])

def run(code: str, *, timeout: int=30, stdin_text: str | None=None) -> dict:
    st = check(code)
    boot = NO_NET_SITECUSTOMIZE
    argv = [sys.executable, '-I', '-S', '-c', f"import sys; sys.argv=['sandbox'];exec({boot!r});import resource as R;R.setrlimit(R.RLIMIT_CPU,({timeout},{timeout}));R.setrlimit(R.RLIMIT_AS,(2*1024**3,2*1024**3));R.setrlimit(R.RLIMIT_NOFILE,(64,64));R.setrlimit(R.RLIMIT_NPROC,(64,64));exec({code!r})"]
    try:
        p = subprocess.run(argv, capture_output=True, text=True, input=stdin_text, timeout=timeout, env={'PATH': '/usr/bin:/bin', 'HOME': '/tmp'}, cwd='/tmp')
        out, err, rc = (p.stdout or '', p.stderr or '', p.returncode)
        if rc != 0:
            return {'ok': False, 'output': err or out, 'error': f'exit {rc}', 'returncode': rc}
        return {'ok': True, 'output': out, 'returncode': rc, 'error': ''}
    except subprocess.TimeoutExpired:
        return {'ok': False, 'error': f'timed out after {timeout}s (hard kill)', 'output': '', 'returncode': -9}
    except Exception as e:
        return {'ok': False, 'error': f'{type(e).__name__}: {e}', 'output': '', 'returncode': -1}