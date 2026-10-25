from __future__ import annotations
import shutil
from pathlib import Path
_BIN_CACHE: dict = {}

def which(bin_name: str) -> str:
    if bin_name not in _BIN_CACHE:
        p = shutil.which(bin_name)
        if not p:
            raise FileNotFoundError(f'{bin_name} is not installed on this box')
        _BIN_CACHE[bin_name] = p
    return _BIN_CACHE[bin_name]
_WORDLISTS = ['common', 'medium']

def _wordlist(name: str) -> str:
    tiers = {'common': ['/usr/share/wordlists/dirb/common.txt', '/usr/share/seclists/Discovery/Web-Content/common.txt'], 'medium': ['/usr/share/wordlists/dirbuster/directory-list-2.3-medium.txt', '/usr/share/seclists/Discovery/Web-Content/directory-list-2.3-medium.txt']}
    if '/' in name:
        return name
    for p in tiers.get(name, []):
        if Path(p).exists():
            return p
    raise FileNotFoundError(f"wordlist tier '{name}' not found on this box (checked: {', '.join(tiers.get(name, [])) or 'unknown tier'})")

def build_scan(scan_type: str, target: str, *, ports: str | None=None, wordlist: str='common', threads: int=10, extra_flags: list | None=None) -> list:
    extra_flags = list(extra_flags or [])
    t = scan_type
    if t == 'nmap_quick':
        argv = [which('nmap'), '-Pn', f"-p{ports or 'top'}", '-T3']
    elif t == 'nmap_full':
        argv = [which('nmap'), '-sS', '-sV', '-O', '-p' + (ports or '1-65535')]
    elif t == 'nmap_vuln':
        argv = [which('nmap'), '-sV', '--script=vuln', '-p' + (ports or 'top')]
    elif t == 'gobuster':
        wlp = _wordlist(wordlist)
        argv = [which('gobuster'), 'dir', '-w', wlp, '-t', str(threads)]
    elif t == 'ffuf':
        wlp = _wordlist(wordlist)
        argv = [which('ffuf'), '-w', wlp, '-t', str(threads)]
    elif t == 'dirb':
        wlp = _wordlist(wordlist)
        argv = [which('dirb')]
    elif t == 'nikto':
        argv = [which('nikto')]
    else:
        raise ValueError(f'unknown scan_type {t!r}')
    if t in ('nmap_quick', 'nmap_full', 'nmap_vuln'):
        return argv + extra_flags + [target]
    if t == 'gobuster':
        return argv + ['-u', target] + extra_flags
    if t == 'ffuf':
        return argv + ['-u', target.rstrip('/') + '/FUZZ'] + extra_flags
    if t == 'dirb':
        return argv + [target] + extra_flags
    if t == 'nikto':
        return argv + ['-h', target] + extra_flags
    raise ValueError(f'unknown scan_type {t!r}')

def build_ssl(target: str, port: int | str=443) -> list:
    return [which('openssl'), 's_client', '-connect', f'{target}:{port}']

def build_dns(target: str) -> list:
    return [which('dig'), '+short', target]

def build_whatweb(target: str) -> list:
    return [which('whatweb'), target]