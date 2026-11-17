"""Greypentest scan builders — argv templates, never shell strings.

Every scanner call is constructed as an ARGV list whose FIRST token is the
binary's absolute path (resolved at build time with shutil.which and cached).
Execution goes through exec_gate (absolute-path allowlist, timeout-capped).
Templates: nmap quick/full/vuln, gobuster, ffuf, dirb, nikto, plus the
asset wrappers ssl (openssl), subdomain (dig), tech (whatweb).
"""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

_BIN_CACHE: dict = {}

_ROOT = Path(__file__).resolve().parent.parent
# Resolution order: THIS suite's bin/ first (USB-isolated, policy uses
# $ROOT/bin/...), then non-PATH system homes (go installs, pip user scripts).
_EXTRA_DIRS = [str(_ROOT / "bin"),
               os.path.expanduser("~/go/bin"),
               os.path.expanduser("~/.local/bin")]


def _find_bin(bin_name: str) -> str | None:
    # VENDORED FIRST: the suite's own bin/ wins over whatever PATH offers, so
    # an installed-elsewhere lookalike can never shadow the suite binary.
    for d in _EXTRA_DIRS:
        c = os.path.join(d, bin_name)
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return shutil.which(bin_name)


def which(bin_name: str) -> str:
    """Resolve a bare scanner name to the BARE NAME token (2026-10-30
    greypentest: installed-tools model). The existence check is real — raises
    FileNotFoundError when the tool isn't installed — but builders emit the
    bare NAME as argv[0]; exec_gate.check() then resolves it against its own
    trusted dirs and runs the absolute path it found there. Returning the
    absolute path here made the gate's allowlist (bare tool names) deny every
    scanner. Raises FileNotFoundError when the tool isn't on this box."""
    if bin_name not in _BIN_CACHE:
        p = _find_bin(bin_name)
        if not p:
            raise FileNotFoundError(
                f"{bin_name} is not installed on this box — "
                "tool_check/tool_install can get it")
        _BIN_CACHE[bin_name] = bin_name
    return _BIN_CACHE[bin_name]


_WORDLISTS = ["common", "medium"]

# STEALTH defaults (owner directive 2026-10-30): every tool runs low-and-slow —
# 1–2 workers with a per-request delay, human-scale request rates, and a
# browser User-Agent so the target sees traffic indistinguishable from a
# patient human. The first live run took a rate-limited IONOS host down with
# 10-thread crawls; these defaults exist so that never happens again.
# Caller-thread caps: build_scan clamps whatever it is handed.
_MAX_THREADS = 2
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def _wordlist(name: str) -> str:
    """The named tier → the real wordlist file. This suite's vendored copies
    (bin-data/wordlists) resolve FIRST so wordlists travel with the folder;
    system paths stay as fallbacks. Bare words are keys, not paths; a wrong
    path is a loud error, not a silent guess."""
    tiers = {"common": [str(_ROOT / "bin-data" / "wordlists" / "common.txt"),
                        "/usr/share/wordlists/dirb/common.txt",
                        "/usr/share/seclists/Discovery/Web-Content/common.txt"],
             "medium": [str(_ROOT / "bin-data" / "wordlists"
                            / "directory-list-2.3-medium.txt"),
                        "/usr/share/wordlists/dirbuster/directory-list-2.3-medium.txt",
                        "/usr/share/seclists/Discovery/Web-Content/directory-list-2.3-medium.txt"]}
    if "/" in name:
        return name                          # caller gave the path directly
    for p in tiers.get(name, []):
        if Path(p).exists():
            return p
    raise FileNotFoundError(
        f"wordlist tier '{name}' not found on this box "
        f"(checked: {', '.join(tiers.get(name, [])) or 'unknown tier'})")


def build_scan(scan_type: str, target: str, *, ports: str | None = None,
               wordlist: str = "common", threads: int = 10,
               extra_flags: list | None = None) -> list:
    extra_flags = list(extra_flags or [])
    # case-insensitive scan types: the pipeline used to crash on a model's
    # "theHarvester" while the builder compared "theharvester" — and the
    # crash DISCARDED prior lanes' results (2026-10-31 audit P0)
    t = scan_type.strip().lower()
    # STEALTH: cap caller threads at the stealth ceiling — whatever the model
    # asked for, no crawl tool exceeds _MAX_THREADS workers.
    threads = min(max(1, threads), _MAX_THREADS)
    if t == "nmap_quick":
        # nmap 7.95 rejects bare -pT; T:1-65535 = top 1000 ports (the quick default).
        # -T2 polite timing + --max-rate 30 keeps the port sweep under the
        # rate-limiting floor of shared hosts (stealth, not -T3 machine-gun).
        argv = [which("nmap"), "-Pn", f"-p{ports or 'T:1-65535'}", "-T2",
                "--max-rate", "30"]
    elif t == "nmap_full":
        argv = [which("nmap"), "-sT", "-sV", "-T2", "--max-rate", "30",
                "-p" + (ports or "1-65535")]
    elif t == "nmap_vuln":
        argv = [which("nmap"), "-sV", "--script=vuln", "-T2", "--max-rate", "25",
                "-p" + (ports or "T:1-65535")]
    elif t == "gobuster":
        wlp = _wordlist(wordlist)
        # --delay 500ms per thread; with -t 2 that's ~4 req/s ceiling.
        argv = [which("gobuster"), "dir", "-w", wlp, "-t", str(threads),
                "--delay", "500ms"]
    elif t == "ffuf":
        wlp = _wordlist(wordlist)
        # -X GET: ffuf defaults to POST, which is the wrong verb for a
        # directory brute-force (servers 405 POST to paths that GET fine).
        # -rate 8 caps req/s regardless of threads; -p 0.4 sleeps between.
        argv = [which("ffuf"), "-w", wlp, "-X", "GET", "-t", str(threads),
                "-rate", "8", "-p", "0.4",
                "-H", f"User-Agent: {_UA}"]
    elif t == "dirb":
        wlp = _wordlist(wordlist)
        argv = [which("dirb")]
    elif t == "nikto":
        # -Pause 2 s between tests (this build has no thread flag — pause is
        # the stealth lever), 30 s request timeout, no interactive ask, and
        # browser User-Agent via -useragent.
        argv = [which("nikto"), "-Pause", "2", "-timeout", "30",
                "-ask", "no", "-useragent", _UA]
    elif t == "sqlmap":
        # sqlmap is a URL scanner (not a wordlist/dir tool). -q quiet, --batch
        # so it never blocks on an interactive prompt; --threads 1 --delay 1
        # keeps injection probing to human-scale pacing.
        argv = [which("sqlmap"), "--batch", "-q", "--threads=1",
                "--delay=1", "--time-sec=10"]
    elif t == "nuclei":
        # JSONL (one JSON object per finding) — the parser in webpentest
        # reads it line-wise. -c 1 concurrency and -rl 8 req/s cap; browser UA.
        argv = [which("nuclei"), "-j", "-nc", "-c", "1", "-rl", "8",
                "-timeout", "20"]
    elif t == "feroxbuster":
        wlp = _wordlist(wordlist)
        # --no-state silences the status-table footer (parser noise).
        # --delay 500 (ms per request) × -t 2 ≈ 4 req/s ceiling; browser UA.
        argv = [which("feroxbuster"), "-w", wlp, "-t", str(threads),
                "--delay", "500", "-a", _UA, "--no-state", "--quiet"]
    elif t == "httpx":
        # -timeout 15 + -retries 1 ends parked sockets quickly (the live run
        # showed a rate-limited host can stall httpx until its 1h budget);
        # -rl 10 req/s cap.
        argv = [which("httpx"), "-title", "-tech-detect", "-status-code",
                "-location", "-no-color", "-timeout", "15",
                "-retries", "1", "-rl", "10"]
    elif t == "katana":
        # Standard mode, no JS parsing (headless chrome crawl is opt-in via
        # extra_flags). -c 2 fetchers + -rd 1 (1 s request delay); browser UA.
        argv = [which("katana"), "-u", target, "-d", "3", "-c", "2", "-rd", "1",
                "-H", f"User-Agent: {_UA}", "-nc", "-silent"]
    elif t == "naabu":
        # Fast port scan; -Pn (no host discovery, hosts may drop ICMP).
        # This naabu build exposes -ports (not -p) and takes named tiers
        # ('top-100', 'full') or a custom list. -rate 100 caps packet rate.
        argv = [which("naabu"), "-Pn", "-silent", "-rate", "100"]
    elif t == "dalfox":
        # ACTIVE XSS scanner (sends payloads) — opt-in, model gates it.
        # --worker 1 --delay 1.2 keeps payload firing human-scale.
        argv = [which("dalfox"), "url", "--no-color", "--no-spinner",
                "--worker", "1", "--delay", "1.2"]
    elif t == "arjun":
        # ACTIVE parameter miner — opt-in. --stable = 1 thread + built-in
        # throttling (prefer stability over speed); --disable-cache.
        argv = [which("arjun"), "--disable-cache", "--stable", "-t", "1"]
    elif t == "wafw00f":
        # Passive WAF fingerprinting — safe for the default flow.
        argv = [which("wafw00f"), "-a"]
    elif t == "subfinder":
        # Passive subdomain discovery (certificate transparency, no packets
        # fired at the target) — passive recon phase, safe default.
        argv = [which("subfinder"), "-silent", "-all"]
    elif t == "dnsx":
        argv = [which("dnsx"), "-silent"]
    elif t == "maigret":
        # OSINT Layer 1: username footprint across public platforms.
        argv = [which("maigret"), "--no-color", "--timeout", "10"]
    elif t == "sherlock":
        # OSINT Layer 1: username lookup fallback (both readers, dedup upstream).
        argv = [which("sherlock"), "--timeout", "10"]
    elif t == "exiftool":
        # OSINT Layer 1: metadata in files/photos (geotags, device serials).
        argv = [which("exiftool")]
    elif t == "ssh_audit":
        # Depth tier (Linux/macOS/any SSH): cipher/algorithm/KEX grading.
        argv = [which("ssh-audit")]
    elif t == "enum4linux_ng":
        # Depth tier (Windows/Samba): users, shares, policy — modern SMB.
        argv = [which("enum4linux-ng"), "-A"]
    elif t == "nbtscan":
        # Depth tier (Windows networks): NetBIOS name sweep.
        argv = [which("nbtscan")]
    elif t == "nxc":
        # MODERN (verified 2026-10-30, actively maintained): NetExec — the
        # CrackMapExec successor. Verifies ACCESS, not just openness:
        # protocol + target (e.g. "smb"); stealth = single connection attempt
        # per phase, no spraying unless the operator authorizes active.
        argv = [which("nxc"), "-t", "1", "--timeout", "15", "--no-color"]
    elif t == "testssl":
        # MODERN TLS depth: testssl.sh grades protocols/ciphers/vulnerabilities
        # that sslscan only skims; --hints --warnings off keeps output parseable.
        argv = [which("testssl"), "-q", "-P", "-U"]
    elif t == "amass":
        # MODERN subdomain enumeration: OWASP Amass, PASSIVE mode only by
        # default (certificate transparency + open archives; no target traffic).
        argv = [which("amass"), "enum", "-passive"]
    elif t == "waymore":
        # MODERN web depth: URL-archive discovery (Wayback/Common Crawl
        # mirrors) — passive, shows real endpoints users actually hit.
        argv = [which("waymore"), "-mode", "U"]
    elif t == "theharvester":
        # MODERN OSINT: emails/subdomains/hosts from public sources.
        argv = [which("theHarvester")]
    elif t == "blackbird":
        # MODERN OSINT (verified 2026-10-30): username+email search across
        # 600+ sites (WhatsMyName data), PDF export.
        argv = [which("blackbird")]
    if t == "maigret":
        return argv + extra_flags + [target]
    if t == "sherlock":
        return argv + extra_flags + [target]
    if t == "exiftool":
        return argv + extra_flags + [target]
    if t in ("ssh_audit", "enum4linux_ng", "nbtscan"):
        # Depth tier: target is the final positional (nbtscan takes a CIDR /
        # range; enum4linux-ng -A <host>; ssh-audit <host>[:port]).
        return argv + extra_flags + [target]
    if t == "nxc":
        # nxc <protocol> <target> — protocol comes first (2026-10-31 fix: the
        # builder omitted it and nxc refuses to run without one). The protocol
        # is popped from extra_flags when the caller passes one; otherwise it
        # defaults to smb (the most common first question: "can I even
        # authenticate to this host?").
        _NXC = {"smb", "ldap", "winrm", "mssql", "ssh", "ftp", "rdp", "http"}
        proto = next((e for e in extra_flags if str(e).lower() in _NXC), "smb")
        extra_flags = [e for e in extra_flags if str(e).lower() not in _NXC]
        return argv + [proto, target] + extra_flags
    if t in ("testssl",):
        return argv + [target] + extra_flags
    if t == "amass":
        # amass enum -passive -d <domain>
        return argv + ["-d", target] + extra_flags
    if t == "waymore":
        # waymore needs the target via -i (input domain)
        return argv + ["-i", target] + extra_flags
    if t in ("theharvester", "blackbird"):
        # theHarvester: -d <domain> -b all; blackbird (p1ngul1n0 vendored):
        # -u <username> for handles, -e <email> for emails — pick by shape.
        if t == "theharvester":
            return argv + ["-d", target, "-b", "all"] + extra_flags
        flag = "-e" if "@" in target else "-u"
        return argv + [flag, target] + extra_flags
    if t in ("nmap_quick", "nmap_full", "nmap_vuln"):
        return argv + extra_flags + [target]
    if t == "gobuster":
        return argv + ["-u", target] + extra_flags
    if t == "ffuf":
        return argv + ["-u", target.rstrip("/") + "/FUZZ"] + extra_flags
    if t == "dirb":
        # dirb usage: dirb [url] [wordlist] [options] — the resolved tier file
        # must be passed, and -z (request delay, ms) comes AFTER it.
        return argv + [target, wlp, "-z", "300"] + extra_flags
    if t == "nikto":
        return argv + ["-h", target] + extra_flags
    if t == "sqlmap":
        # sqlmap takes the URL (with its query string) as the final arg.
        return argv + extra_flags + [target]
    if t == "nuclei":
        return argv + ["-u", target] + extra_flags
    if t == "feroxbuster":
        return argv + ["-u", target] + extra_flags
    if t == "httpx":
        # httpx probes take the URL (or host) as positional input via stdin
        # is disabled in exec_gate, so use -u (single target).
        return argv + ["-u", target] + extra_flags
    if t == "katana":
        return argv + extra_flags
    if t == "naabu":
        # The `-pT:...` tier syntax is nmap-only; naabu wants bare port specs
        # via -ports ("top-100", "top-1000", "full", or a custom list).
        if not ports:
            portspec = "full"
        else:
            p = ports.replace("T:", "")
            portspec = ("top-1000" if p == "T:1-65535"
                        else ("full" if p == "1-65535" else p))
        return argv + ["-host", target, "-ports", portspec] + extra_flags
    if t == "dalfox":
        return argv + [target] + extra_flags
    if t == "arjun":
        return argv + ["-u", target] + extra_flags
    if t == "wafw00f":
        return argv + [target] + extra_flags
    if t == "subfinder":
        return argv + ["-d", target] + extra_flags
    if t == "dnsx":
        return argv + ["-d", target] + extra_flags
    raise ValueError(f"unknown scan_type {t!r}")


def build_ssl(target: str, port: int | str = 443) -> list:
    # No -batch: OpenSSL 3.x s_client does not accept it (it's an s_server /
    # general option, not an s_client one), and it errors out. stdin is closed
    # by the caller (exec_gate.run(stdin_text="")), which is what stops
    # s_client from waiting for interactive input on a self-signed cert.
    # 2026-10-31: models pass whole URLs ("https://host"); strip scheme/path
    # so openssl gets a clean "host:port" (was erroring: '-connect argument
    # malformed'). Revert nothing — the -batch comment above still stands.
    t = str(target).strip()
    t = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", "", t)
    t = t.split("/", 1)[0]
    return [which("openssl"), "s_client", "-connect", f"{t}:{port}"]


def build_dns(target: str) -> list:
    return [which("dig"), "+short", target]


def build_whatweb(target: str) -> list:
    # Browser User-Agent: whatweb's default UA identifies it as a scanner instantly.
    return [which("whatweb"), "-U", _UA, target]