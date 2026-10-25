from __future__ import annotations
import ipaddress
import socket
import urllib.parse
import urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
NEVER_NETS = [ipaddress.ip_network('127.0.0.0/8'), ipaddress.ip_network('169.254.0.0/16'), ipaddress.ip_network('0.0.0.0/8'), ipaddress.ip_network('::1/128'), ipaddress.ip_network('fe80::/10')]

class HttpDeny(Exception):
    pass

def _policy_scope():
    try:
        import json
        data = json.loads((ROOT / 'policy.json').read_text())
        scope = data.get('http', {})
    except Exception as e:
        raise HttpDeny(f'policy unreadable → deny ({e})')
    return scope

def _check_url(url: str) -> tuple[str, int, bool]:
    pr = urllib.parse.urlsplit(url)
    if pr.scheme not in ('http', 'https'):
        raise HttpDeny(f'scheme {pr.scheme!r} not allowed')
    host = pr.hostname
    if not host:
        raise HttpDeny('no host')
    scope = _policy_scope()
    explicit = set(scope.get('allow', [])) | set(scope.get('allow_hosts', []))
    if url in explicit or host in explicit:
        return (host, pr.port or (443 if pr.scheme == 'https' else 80), bool(scope.get('tls_insecure')))
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise HttpDeny(f'dns fail → deny ({e})')
    ips = {i[4][0] for i in infos}
    forbidden = {ip for ip in ips if any((ipaddress.ip_address(ip) in n for n in NEVER_NETS))}
    if forbidden:
        raise HttpDeny('forbidden address class (localhost/link-local/metadata) — unreachable through the gate, no exception exists')
    lab_nets = [ipaddress.ip_network(n) for n in scope.get('lab_nets', [])]
    if not lab_nets:
        raise HttpDeny(f'host {host!r} not on the lab allowlist')
    if not any((ipaddress.ip_address(ip) in n for ip in ips for n in lab_nets)):
        raise HttpDeny(f'host {host!r} ({sorted(ips)[0]}…) outside lab scope')
    return (host, pr.port or (443 if pr.scheme == 'https' else 80), bool(scope.get('tls_insecure')))

def fetch(url: str, *, method: str='GET', headers: dict | None=None, timeout: int=20, data=None) -> dict:
    host, port, tls_insecure = _check_url(url)
    req = urllib.request.Request(url, method=method, headers=headers or {}, data=data)
    ctx = None
    if url.startswith('https') and tls_insecure:
        import ssl
        ctx = ssl._create_unverified_context()
    try:
        opener = urllib.request.build_opener()
        if ctx:
            import ssl as _s
            opener.add_handler(urllib.request.HTTPSHandler(context=ctx))
        r = opener.open(req, timeout=timeout)
        body = r.read(1000000)
        return {'ok': True, 'status': r.status, 'headers': dict(r.headers), 'body': body.decode(errors='replace')}
    except HttpDeny:
        raise
    except Exception as e:
        return {'ok': False, 'error': f'{type(e).__name__}: {e}', 'status': 0}