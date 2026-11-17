"""Greypentest authorization & agreement generator.

Renders the legal-cover document for an assessment: a signed-format
Authorization & Rules-of-Engagement Agreement (HTML + PDF) in the same RBSC
house style as the reports, from the assessment store's target/scope data.
Called by the MCP tool `agreement_generate` right after the initial test so
the authorization paper trail exists before the engagement continues.
"""
from __future__ import annotations

import html
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import store
import webpentest

OUT = webpentest.OUT
_ESC = webpentest._esc
_CSS = webpentest._CSS
_BANNER_SVG = webpentest._BANNER_SVG

# Rules of engagement — the standard clauses every engagement runs under.
_ROE = (
    "Destructive testing is prohibited: no denial-of-service, no load or "
    "volume attacks, no attempts to degrade or interrupt service.",
    "Testing is limited to the in-scope target recorded above; anything "
    "outside that scope is out of bounds regardless of reachability.",
    "Interactive/attack-tier tools (SQL injection, XSS payloads, template "
    "vulnerability scans, parameter brute-forcing) run only when the "
    "authorizing party has requested active testing.",
    "Information discovered during testing is confidential to this "
    "engagement: it is stored locally in the assessment database, reported "
    "to the authorized recipient, and not shared with third parties.",
    "No credentials, personal data, or third-party data are exfiltrated, "
    "stored off-site, or used beyond demonstrating the vulnerability.",
    "The authorizing party may stop testing at any time and for any reason; "
    "upon such instruction all activity halts immediately and the state of "
    "the work is reported.",
    "Testing is performed by automated, allowlist-gated tooling with every "
    "command logged; raw evidence and command lines are retained in the "
    "assessment database as the record of activity.",
    "Findings and the final report are technical opinions based on testing "
    "performed at the stated time; they are not warranties of security.",
)


def render_html(assessment: str, *, client: str = "", authorized_by: str = "",
                contact: str = "", notes: str = "") -> str:
    data = webpentest._load(assessment)
    a = data["assessment"]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    name = a.get("name") or assessment
    scope = a.get("scope") or ""
    client = client or a.get("client_name") or "Internal"
    authorized_by = authorized_by or client
    ref = f"AGR-GW-{now[:4]}-{name.upper().replace(' ', '-')[:24]}"
    roe = "\n".join(f"<li>{_ESC(c)}</li>" for c in _ROE)
    sig_rows = "".join(f"<tr><td>{lbl}</td><td class='sigline'></td><td class='dline'></td></tr>"
                       for lbl in ("Authorized by (Client)", "Authorized by (Print name)",
                                   "Performed by", "Date of authorization"))
    return f"""<!doctype html>
<html><head><meta charset='utf-8'><title>{_ESC(ref)} — Authorization &amp; Agreement</title>
<style>{_CSS}
.sigline, .dline {{ border-bottom:1px solid #9c8b7a; }}
.meta td.t {{ color:#8b7360; font-family:"IBM Plex Mono",monospace; font-size:12px; }}
ol.roe {{ padding-left:1.2em; }}
ol.roe li {{ margin-bottom:.55em; }}
.callout {{ border:1px solid #c87f45; background:#fbf7f1; padding:.8em 1em; margin:1em 0; }}
</style></head><body>
<header class='masthead'>
  <div class='brand-line'>{_BANNER_SVG}<div class='brand'>Randy Barham</div></div>
  <table class='mast-meta'><tr>
    <td>Security Consulting</td>
    <td class='c'><span>Engagement Docs</span><span>Authorization &amp; Agreement</span></td>
    <td class='r'>{_ESC(now)}</td>
  </tr></table>
</header>

<div class='kicker'>Authorization — written consent for penetration testing</div>
<h1 id='authorization-agreement'>{_ESC(name)} — Authorization &amp; Agreement</h1>
<p class='subtitle'>This document is the authorization to test and the rules of
engagement both parties operate under. It is the legal cover for the activity
documented in the associated report.</p>

<div class='cite-line'>
  <b>{_ESC(ref)} · v1.0</b>
  &nbsp;·&nbsp; Client: {_ESC(client)}
  &nbsp;·&nbsp; Engagement: {_ESC(name)}
  &nbsp;·&nbsp; Sensitive and Proprietary
</div>

<table class='meta'><tr><td>Client</td><td>{_ESC(client)}</td>
<td>Consultant</td><td>Randy Barham, Security Consulting</td></tr>
<tr><td>In-scope target</td><td>{_ESC(scope)}</td>
<td>Test date</td><td>{_ESC(now)}</td></tr>
<tr><td>Audited activity</td><td>Automated web/WordPress penetration testing (Greypentest)</td>
<td>Methodology</td><td>NIST SP 800-115 / OWASP WSTG · CVSS v3.1</td></tr></table>

<div class='callout'>
<b>Authorization.</b> The undersigned authorizing party (on behalf of the
client) confirms they are the lawful owner or operator of the in-scope target
{("(<i>" + _ESC(scope) + "</i>) ") if scope else ""}and grants express
permission for security testing of that target as described herein, for the
purpose of identifying and remediating security vulnerabilities.
{("<p class='muted'>Contact for authorization matters: " + _ESC(contact) + "</p>") if contact else ""}
</div>

<h2>1. Rules of engagement</h2>
<p>The following conditions are binding on the testing activity. A violation
of these terms ends the authorization.</p>
<ol class='roe'>{roe}</ol>

<h2>2. Confidentiality and data handling</h2>
<p>All material produced by the testing — tool output, evidence, findings, and
this agreement — is treated as confidential and proprietary. Reports are
delivered only to the authorizing party or their named representatives. No
portion of the results is published without written consent.</p>

<h2>3. Limitation of liability</h2>
<p>Testing is performed with commercially reasonable care using established
non-destructive methodology. The consultant is not liable for pre-existing
defects, unavailability unrelated to the testing, or the client's response to
findings. The client agrees the consultant is not responsible for loss arising
out of the client's failure to remediate reported vulnerabilities.</p>

<h2>4. Term</h2>
<p>This authorization is effective from the date of signature and covers the
single engagement identified above, including re-scans of the same target
within 30 days unless terminated earlier by either party.</p>

{("<h2>5. Special conditions</h2><p>" + _ESC(notes) + "</p>") if notes else ""}

<h2>Signatures</h2>
<table class='meta'>{sig_rows}</table>

<p class='muted' colspan='2'>This document was generated by the Greypentest
automation, recorded in the assessment database, and rendered from the same
store as the associated report. Sign and retain with the engagement files.
&nbsp;·&nbsp; {_ESC(ref)} · Sensitive and Proprietary</p>

<div class='colophon'>Randy Barham Security Consulting · Engagement Docs ·
Generated {_ESC(now)}</div>
</body></html>"""


def generate_agreement(assessment: str, *, client: str = "",
                       authorized_by: str = "", contact: str = "",
                       notes: str = "", pdf: bool = True,
                       open_pdf: bool = True) -> dict:
    """Render the agreement HTML (+ PDF) for an assessment. Returns paths."""
    OUT.mkdir(parents=True, exist_ok=True)
    html_path = OUT / f"{assessment}-agreement.html"
    html_path.write_text(render_html(assessment, client=client,
                                     authorized_by=authorized_by,
                                     contact=contact, notes=notes))
    out = {"ok": True, "assessment": assessment, "html": str(html_path)}
    if pdf:
        pdf_path = OUT / f"{assessment}-agreement.pdf"
        try:
            subprocess.run(
                ["/usr/bin/chromium", "--headless", "--no-sandbox",
                 "--disable-gpu", f"--print-to-pdf={pdf_path}", str(html_path)],
                capture_output=True, timeout=60, check=False)
            if pdf_path.exists():
                out["pdf"] = str(pdf_path)
                # OWNER 2026-10-30: the agreement must be IN FRONT of the
                # operator at first scan — open it as soon as it renders.
                if open_pdf:
                    try:
                        subprocess.Popen(["xdg-open", str(pdf_path)],
                                         stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL,
                                         start_new_session=True)
                        out["opened"] = True
                    except Exception as e:
                        out["opened"] = False
                        out["note"] = f"open failed ({e}) — sign from {pdf_path}"
            else:
                out["pdf"] = None
                out["note"] = "HTML written; PDF render produced no file"
        except Exception as e:
            out["pdf"] = None
            out["note"] = f"PDF render failed: {e}"
    return out