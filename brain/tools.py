"""Greypentest tool availability — installed-tools model (owner 2026-10-30).

The suite ships NO binaries: every scanner must be installed on the host.
Resolution is by trusted absolute dirs (exec_gate._trusted_which), never a
bare -- $PATH search, so a rogue PATH entry can't shadow a tool.

  tool_check()      → status of every known scanner (installed / path / package)
  tool_install(t)   → installs the missing tool's package via the distro
                      package manager (sudo -n first; if that fails, the
                      exact command is returned for the operator to run)

Package names are Debian/Parrot/Kali apt packages. Tools not packaged for
apt get an honest manual_hint instead of a silent guess.
"""
from __future__ import annotations

import subprocess

import scan_builders

# scanner binary → (apt package, manual install hint for non-packaged tools)
TOOL_PACKAGES: dict[str, tuple[str, str]] = {
    "nmap":      ("nmap", ""),
    "sslscan":   ("sslscan", ""),
    "nikto":     ("nikto", ""),
    "gobuster":  ("gobuster", ""),
    "dirb":      ("dirb", ""),
    "whatweb":   ("whatweb", ""),
    "sqlmap":    ("sqlmap", ""),
    "ffuf":      ("ffuf", ""),
    "wafw00f":   ("wafw00f", ""),
    "arjun":     ("arjun", ""),
    "dig":       ("dnsutils", ""),
    "dnsrecon":  ("dnsrecon", ""),
    "masscan":   ("masscan", ""),
    "unicornscan": ("unicornscan", ""),
    "onesixtyone": ("onesixtyone", ""),
    "snmpwalk":  ("snmp", ""),
    "smbclient": ("smbclient", ""),
    "enum4linux": ("enum4linux", ""),
    "hydra":     ("hydra", ""),
    "medusa":    ("medusa", ""),
    "wp-cli":    ("wp-cli", ""),
    # depth tier (devices/network verify pipeline)
    "nbtscan":   ("nbtscan", ""),
    "ssh-audit": ("ssh-audit", "pip3 install ssh-audit"),
    "lynis":     ("lynis", ""),
    "exiftool":  ("libimage-exiftool-perl", ""),
    "adb":       ("android-tools-adb", ""),
    "ideviceinfo": ("libimobiledevice-utils", ""),
    # OSINT suite (python CLI tools — pipx/pip user installs)
    # modern replacements (verified maintained 2026-10-30)
    "nxc":       ("", "pipx install git+https://github.com/Pennyw0rth/NetExec"),
    "testssl":   ("testssl.sh", ""),
    "amass":     ("", "go install github.com/owasp-amass/amass/v4/...@master"),
    "waymore":      ("", "pip3 install --user waymore"),
    # secret scanning (greypentest_mcp scan_type=gitleaks: git clone + gitleaks dir)
    "gitleaks":  ("gitleaks", ""),
    "gitfive":   ("", "pip3 install --user --break-system-packages gitfive  "
                      "# MANUAL ONLY: demands a GitHub username/password login"),
    "phonenumbers": ("", "pip3 install --user --break-system-packages phonenumbers"),
    # projectdiscovery tools: not in Debian repos on every distro
    "nuclei":    ("", "go install github.com/projectdiscovery/nuclei/v2/cmd/nuclei@latest"),
    "httpx":     ("", "go install github.com/projectdiscovery/httpx/cmd/httpx@latest"),
    "katana":    ("", "go install github.com/projectdiscovery/katana/cmd/katana@latest"),
    "subfinder": ("", "go install github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest"),
    "naabu":     ("", "go install github.com/projectdiscovery/naabu/v2/cmd/naabu@latest"),
    "dnsx":      ("", "go install github.com/projectdiscovery/dnsx/cmd/dnsx@latest"),
    "dalfox":    ("", "go install github.com/hahwul/dalfox/v2@latest"),
    # URL-history sources (bounty recon: archived endpoints + params)
    "gau":         ("", "go install github.com/lc/gau/v2/cmd/gau@latest"),
    "waybackurls": ("", "go install github.com/tomnomnom/waybackurls@latest"),
    # interactive proxies (MANUAL use; NOT throttled by scan_builders —
    # operator must keep low-and-slow pacing by hand)
    "mitmproxy": ("mitmproxy", ""),
    "zaproxy":   ("zaproxy", "apt zaproxy (OWASP ZAP CLI); GUI = zaproxy -u"),
    "burpsuite": ("", "MANUAL: java + Burp jar from portswigger.net/download"),
    # screenshots + misc web recon
    "gowitness": ("", "go install github.com/sensepost/gowitness@latest"),
    # already-driven by builders but previously unregistered
    "feroxbuster": ("", "MANUAL: cargo build --release / release binary at feroxbuster releases"),
    "openssl":     ("openssl", ""),
    "enum4linux-ng": ("", "pip3 install --user enum4linux-ng"),
}

def _installed(bin_name: str) -> str | None:
    try:
        return scan_builders.which(bin_name)
    except FileNotFoundError:
        return None


def tool_missing(bin_name: str) -> dict:
    """Honest availability answer for one binary, with the install path."""
    entry = TOOL_PACKAGES.get(bin_name)
    path = _installed(bin_name)
    return {"bin": bin_name, "installed": bool(path), "path": path,
            "package": (entry[0] or None) if entry else None,
            "manual_hint": (entry[1] or None) if entry else None}


def tool_check(bins: list[str] | None = None) -> dict:
    names = list(bins) if bins else list(TOOL_PACKAGES)
    out = {}
    for n in names:
        path = _installed(n)
        out[n] = {
            "installed": bool(path),
            "path": path,
            "package": TOOL_PACKAGES.get(n, ("", ""))[0] or None,
            "manual": TOOL_PACKAGES.get(n, ("", ""))[1] or None,
        }
    return {"ok": True, "tools": out,
            "missing": [n for n in names if not out[n]["installed"]]}


def _sudo_available() -> bool:
    p = subprocess.run(["sudo", "-n", "true"], capture_output=True,
                       timeout=10)
    return p.returncode == 0


def tool_install(bin_name: str) -> dict:
    entry = TOOL_PACKAGES.get(bin_name)
    if entry is None:
        return {"ok": False,
                "error": f"unknown tool '{bin_name}' — only tools the suite "
                         "knows about can be installed"}
    pkg, manual = entry
    path = _installed(bin_name)
    if path:
        return {"ok": True, "already": True, "path": path,
                "note": f"{bin_name} already installed at {path}"}
    if not pkg:
        return {"ok": False, "error": f"{bin_name} has no apt package",
                "manual_hint": manual}
    if not _sudo_available():
        return {"ok": False, "error":
                "no passwordless sudo — install it yourself with:",
                "command": f"sudo apt-get install -y {pkg}",
                "package": pkg}
    p = subprocess.run(
        ["sudo", "-n", "apt-get", "install", "-y", "--no-install-recommends", pkg],
        capture_output=True, text=True, timeout=600)
    path = _installed(bin_name)
    return {
        "ok": bool(path) or p.returncode == 0,
        "installed_path": path,
        "package": pkg,
        "output": (p.stdout + p.stderr)[-4_000:],
    }