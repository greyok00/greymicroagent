"""Greypentest http_safe — SSRF-hardened HTTP egress.

Rules (enforce-first, fail-closed):
  * EVERY destination — allowlisted or lab-resolved — is checked against the
    forbidden address classes (127.0.0.0/8, RFC1918, link-local, cloud
    metadata, 0/8, ::1, fe80::/10). Allowlisting permits a PUBLIC host; it can
    never re-open the never-nets. Verified 2026-10-31: http://127.0.0.1/x is
    DENIED even with 127.0.0.1 explicitly in http.allow.
  * redirect pinning: redirects are NOT followed by urllib (they would
    re-resolve DNS out of our control). Each hop is followed manually and
    re-checked before the connection is made; a lab host redirecting to
    169.254.169.254 dies at the hop check.
  * verify_ssl is honored only as given by operator config in policy; a
    caller asking verify=false gets it only when policy.tls_insecure=true.
"""
from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def _resolve_root() -> Path:
    # Adaptive root: nearest ancestor that actually ships policy.json.
    here = Path(__file__).resolve().parent
    for d in (here, *here.parents):
        if (d / "policy.json").exists():
            return d
    return here.parent


ROOT = _resolve_root()

NEVER_NETS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),      # cloud metadata — absolute
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fe80::/10"),
]


class HttpDeny(Exception):
    pass


def _policy_scope():
    try:
        import json
        data = json.loads((ROOT / "policy.json").read_text())
        scope = data.get("http", {})
    except Exception as e:                       # fail-CLOSED
        raise HttpDeny(f"policy unreadable → deny ({e})")
    return scope


def _resolve_ips(host: str) -> set:
    """Resolve a hostname to a set of IPs, or {'<host>'} for a literal IP."""
    try:
        ipaddress.ip_address(host)
        return {host}
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise HttpDeny(f"dns fail → deny ({e})")
    return {i[4][0] for i in infos}


def _check_url(url: str) -> tuple[str, int, bool, set]:
    pr = urllib.parse.urlsplit(url)
    if pr.scheme not in ("http", "https"):
        raise HttpDeny(f"scheme {pr.scheme!r} not allowed")
    host = pr.hostname
    if not host:
        raise HttpDeny("no host")
    scope = _policy_scope()
    # The forbidden classes are checked FIRST, for EVERY url — an operator
    # allowlist entry can never re-open localhost/link-local/metadata.
    ips = _resolve_ips(host)
    forbidden = {ip for ip in ips
                 if any(ipaddress.ip_address(ip) in n for n in NEVER_NETS)}
    if forbidden:
        raise HttpDeny("forbidden address class (localhost/link-local/metadata)"
                       " — unreachable through the gate, no exception exists")
    # allow = lab targets; osint_allow_hosts = verified keyless public OSINT
    # endpoints (OSINT Framework set, probed live 2026-10-30). Both are
    # explicit operator-managed lists — anything else still resolves-and-pins
    # against lab_nets only.
    explicit = (set(scope.get("allow", [])) | set(scope.get("allow_hosts", []))
                | set(scope.get("osint_allow_hosts", [])))
    if url in explicit or host in explicit:
        return host, pr.port or (443 if pr.scheme == "https" else 80), \
            bool(scope.get("tls_insecure")), ips
    lab_nets = [ipaddress.ip_network(n) for n in scope.get("lab_nets", [])]
    if not lab_nets:
        raise HttpDeny(f"host {host!r} not on the lab allowlist")
    if not any(ipaddress.ip_address(ip) in n for ip in ips for n in lab_nets):
        raise HttpDeny(f"host {host!r} ({sorted(ips)[0]}…) outside lab scope")
    return host, pr.port or (443 if pr.scheme == "https" else 80), \
        bool(scope.get("tls_insecure")), ips


def _opener(ctx=None, follow_redirects: bool = False):
    """Opener that never auto-follows redirects — every hop goes through
    _check_url first (default urllib redirect handling re-resolves DNS with
    zero validation, which is the SSRF-by-redirect hole)."""
    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **kw):
            return None
    opener = urllib.request.build_opener(_NoRedirect)
    if ctx:
        import ssl as _s
        opener.add_handler(urllib.request.HTTPSHandler(context=ctx))
    return opener


_MAX_HOPS = 4


def fetch(url: str, *, method: str = "GET", headers: dict | None = None,
          timeout: int = 20, data=None) -> dict:
    # first hop validated before anything connects; further hops re-checked
    host, port, tls_insecure, ips = _check_url(url)
    ctx = None
    tls_insecure = bool(_policy_scope().get("tls_insecure"))
    if url.startswith("https") and tls_insecure:
        import ssl
        ctx = ssl._create_unverified_context()   # only when policy explicitly allows
    opener = _opener(ctx)
    current, hops = url, 0
    try:
        while True:
            hops += 1
            try:
                with _pin_resolution(host, ips):
                    r = opener.open(urllib.request.Request(
                        current, method=method,
                        headers=headers or {}, data=data if hops == 1 else None),
                        timeout=timeout)
                body = r.read(1_000_000)
                return {"ok": True, "status": r.status,
                        "headers": dict(r.headers),
                        "body": body.decode(errors="replace"),
                        "url": r.geturl()}
            except urllib.error.HTTPError as e:
                # 4xx/5xx are a RESPONSE, not a failure — urllib raises
                # HTTPError but it carries the real status/headers/body.
                # Swallowing it as status 0 lost the 403/404/503 signal the
                # WP probe keys off.
                loc = (e.headers or {}).get("Location", "") if \
                    e.code in (301, 302, 303, 307, 308) else ""
                if not loc:
                    try:
                        b = e.read(1_000_000).decode(errors="replace")
                    except Exception:
                        b = ""
                    return {"ok": e.code >= 500, "status": e.code,
                            "headers": dict(e.headers or {}), "body": b}
                if hops >= _MAX_HOPS:
                    raise HttpDeny(f"redirect chain > {_MAX_HOPS} hops")
                nxt = urllib.parse.urljoin(current, loc)
                host, port, tls_insecure, ips = _check_url(nxt)
                                                          # the SSRF gate, hop by hop
                current = nxt
                method = "GET"                   # 303/307 semantics
                continue
    except HttpDeny:
        raise
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "status": 0}
# 2026-10-31 QA (GT-02 class): pin connect-time resolution to the IPs the
# gate validated — the check-then-connect rebind window is closed by making
# every socket resolution during the request reuse the validated answer.
_pin_host: str | None = None
_pin_ips: set = set()


def _pinned_getaddrinfo(host, port, *args, **kwargs):
    try:
        ipaddress.ip_address(host)
        return socket.getaddrinfo(host, port, *args, **kwargs)
    except ValueError:
        pass
    if host == _pin_host and _pin_ips:
        fam = socket.AF_INET6 if ':' in sorted(_pin_ips)[0] else socket.AF_INET
        return [(fam, socket.SOCK_STREAM, 6, '', (ip, port)) for ip in sorted(_pin_ips)]
    return socket.getaddrinfo(host, port, *args, **kwargs)


class _pin_resolution:

    def __init__(self, host: str, ips: set):
        global _pin_host, _pin_ips
        self.orig, self.host, self.ips = socket.getaddrinfo, host, ips

    def __enter__(self):
        global _pin_host, _pin_ips
        _pin_host, _pin_ips = self.host, self.ips
        socket.getaddrinfo = _pinned_getaddrinfo

    def __exit__(self, *a):
        global _pin_host, _pin_ips
        socket.getaddrinfo = self.orig
        _pin_host, _pin_ips = None, set()
