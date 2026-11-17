"""LEAD EXPANSION — find the next thread to pull.

After a suite captures data (osint lookups, capture_data/harvest_data pulls,
finding cards), this module mines the assessment store for identifiers that
deserve their own follow-up search: emails, phone numbers, domains/hosts,
IP addresses, and account handles. Each lead gets:

  * where it was found in THIS assessment (never invented, never carried over
    from a tool banner — example.com/test data is filtered out),
  * a plain-language note on why it matters to the engagement,
  * a ready-made search query,
  * an optional greysearch deep-research run (background) fired for the
    strongest leads,
  * and a "Follow-Up Leads" appendix rendered to HTML + PDF in the house
    style, next to the main report.

Import-only relation to greysearch (that project is off-limits to modify):
the compiled greysearch_mcp module exposes dispatch("greysearch", {...}).
"""
from __future__ import annotations

import html
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import store

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "reports"
_ASSETS = Path(__file__).resolve().parent / "report_assets"
_CSS = ((_ASSETS / "engagement.css").read_text()
        + "\n" + (_ASSETS / "print.css").read_text())
_BANNER_SVG = (_ASSETS / "banner.svg").read_text()

# --- extraction ------------------------------------------------------------- #
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_IPV4_RE = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
_DOMAIN_RE = re.compile(r"(?<![\w@.-])((?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+"
                        r"(?:com|net|org|io|dev|me|us|co|uk|ca|de|info|xyz|local"
                        r"|edu|gov|mil|tv|app|shop|site|online|tech|cloud)\b)",
                        re.IGNORECASE)
_PHONE_RE = re.compile(r"(?<![\w\d])(\+?\d(?:[\d\s().-]{7,15})\d)(?![\w\d])")


def _is_phone(match: str) -> bool:
    # unbalanced parens → regex grabbed a fragment around a real token
    if match.count("(") != match.count(")"):
        return False
    digits = re.sub(r"\D", "", match)
    if not 10 <= len(digits) <= 15:
        return False
    # North-American fictional ranges (555-01xx) are placeholder text, not leads
    na = re.fullmatch(r"1?(\d{3})(\d{3})(\d{4})", digits.lstrip("+1")[-10:])
    if na and na.group(2) == "555" and na.group(3).startswith("01"):
        return False
    return True

# Lead-kill list: tool banners, RFC-test values, and lab names must never
# become "leads" about the subject. (The holehe banner bug made this rule.)
_BAD_DOMAIN_PARTS = ("example.", "test.", "dryrun", "lab.local",
                     "localhost", "invalid.")
_TEST_NETS = ("203.0.113.", "192.0.2.", "198.51.100.")


def _esc(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def _keep(value: str) -> bool:
    v = value.lower()
    return not any(p in v for p in _BAD_DOMAIN_PARTS)


# --- collection ------------------------------------------------------------- #
def collect(assessment: str, aliases: list | None = None) -> dict:
    """Mine recon rows + cards for the assessment; classify the identifiers."""
    a = store.load_assessment(assessment)
    subject = (a.get("assessment") or {}).get("name", "")
    cards = store.list_cards(assessment)
    recon = store.list_recon(assessment)

    blobs: list[tuple[str, str]] = []          # (provenance, text)
    for r in recon:
        blobs.append((f"recon[{r['type']}] {r['name']}",
                      json_dump(r.get("name")) + " " + json_dump(r.get("details"))))
    for c in cards:
        blobs.append((f"card[{c['type']}] {c['title']}",
                      c.get("title", "") + " " + json_dump(c.get("detail"))))

    leads: dict[str, dict[str, dict]] = {k: {} for k in
                                         ("email", "domain", "ip", "phone", "alias")}

    def _add(kind: str, value: str, prov: str):
        value = value.strip()
        if not value or not _keep(value):
            return
        bucket = leads[kind].setdefault(value, {"value": value, "found_in": []})
        if prov not in bucket["found_in"] and len(bucket["found_in"]) < 4:
            bucket["found_in"].append(prov)

    for prov, text in blobs:
        for m in _EMAIL_RE.findall(text):
            _add("email", m, prov)
        for m in _IPV4_RE.findall(text):
            s = m
            if not any(s.startswith(n) for n in _TEST_NETS) and \
                    all(int(o) <= 255 for o in s.split(".")):
                _add("ip", s, prov)
        for m in _DOMAIN_RE.findall(text):
            _add("domain", m, prov)
        for m in _PHONE_RE.findall(text):
            if not _is_phone(m):
                continue
            _add("phone", m, prov)
    for al in (aliases or []):
        _add("alias", str(al).strip(), "operator-supplied")

    # counts, strongest-first ordering inside each kind
    for kind in leads:
        leads[kind] = sorted(leads[kind].values(),
                             key=lambda b: -len(b["found_in"]))
    return {"ok": True, "assessment": assessment, "subject": subject,
            "counts": {k: len(v) for k, v in leads.items()}, "leads": leads}


def json_dump(x) -> str:
    try:
        import json as _j
        return _j.dumps(x, ensure_ascii=False, default=str)
    except Exception:
        return str(x)


# --- query construction ----------------------------------------------------- #
_WHY = {
    "email": "A registered email is the single most reusable key: it tells an "
             "attacker where to reset passwords and which of the subject's "
             "services accept that address.",
    "domain": "A domain or host tied to the assessment expands the attack "
              "surface — anything hosted there (mail, panels, forgotten "
              "subdomains) belongs to the same perimeter.",
    "ip": "An address that surfaced in the capture may host services the main "
          "target never mentioned; verifying ownership closes a blind spot.",
    "phone": "A phone number from site content links the subject to "
             "messaging accounts and SMS-based password resets.",
    "alias": "An account handle is the bridge between platforms: the same "
             "alias on a forgotten service is often the softest entry.",
}
_QUERY_T = {
    "email":   '"{v}" exposure OR breach OR paste',
    "domain":  'site:{v} OR "{v}" forgotten subdomains OR panels',
    "ip":      '"{v}" ownership OR reverse DNS OR hosting history',
    "phone":   '"{v}" messaging OR profile OR listings',
    "alias":   '"{v}" account OR profile OR (site:{v})',
}
_FRIENDLY = {"email": "Email address", "domain": "Domain / host",
             "ip": "IP address", "phone": "Phone number", "alias": "Handle / alias"}


def build_queries(leadset: dict, subject: str, max_queries: int = 6) -> list:
    """Rank leads into concrete follow-up searches, strongest evidence first."""
    ranked = []
    order = ("email", "alias", "domain", "ip", "phone")
    for kind in order:
        for b in leadset.get(kind, []):
            ranked.append({
                "kind": kind, "value": b["value"], "found_in": b["found_in"],
                "why": _WHY[kind],
                "query": _QUERY_T[kind].format(v=b["value"]) +
                         (f" ({subject})" if subject and kind == "alias" else ""),
            })
    ranked.sort(key=lambda r: -len(r["found_in"]))
    return ranked[:max(1, int(max_queries))]


# --- greysearch (import-only, never modified) -------------------------------- #
def _gsearch():
    import sys
    gp = "/home/grey/greysearch"
    if gp not in sys.path:
        sys.path.insert(0, gp)
    import greysearch_mcp as g
    return g


def fire(queries: list) -> dict:
    """Start background greysearch runs for the given queries."""
    g = _gsearch()
    fired = []
    for q in queries:
        try:
            r = g.dispatch("greysearch", {"query": q["query"], "background": True})
            fired.append({"query": q["query"], "ok": bool(r.get("ok")),
                          "run_id": r.get("run_id"),
                          "guide_path": r.get("guide_path"),
                          "note": r.get("error", "") if not r.get("ok")
                          else "research run started in background"})
        except Exception as e:
            fired.append({"query": q["query"], "ok": False,
                          "note": f"greysearch unavailable: {type(e).__name__}: {e}"})
    return {"ok": True, "fired": fired}


def poll() -> dict:
    try:
        g = _gsearch()
        h = g.dispatch("greysearch_health", {})
        runs = h.get("greysearch_runs", {}) if isinstance(
            h.get("greysearch_runs"), dict) else h.get("greysearch_runs")
        return {"ok": True, "status": h.get("status", ""),
                "runs": runs if isinstance(runs, list) else runs}
    except Exception as e:
        return {"ok": False, "error": f"greysearch health: {type(e).__name__}: {e}"}


# --- appendix rendering ----------------------------------------------------- #
def render_html(assessment: str, leadset: dict, ranked: list, fired: list) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    subject = _esc(assessment)
    fired_by_q = {f.get("query"): f for f in fired}

    sections = []
    if not ranked:
        sections.append("<p>No reusable identifiers were captured in this "
                        "assessment yet. Run an osint sweep or a capture pass "
                        "first — leads appear there.</p>")
    for r in ranked:
        fr = fired_by_q.get(r["query"])
        status = ("<span class='sev INFO'>RUNNING</span> — the deep-research "
                  "guide will appear at the path shown when finished"
                  if fr and fr.get("ok") else
                  "<span class='sev INFO'>not fired</span> — search manually or "
                  "re-run lead expansion with fire enabled" if fr is None else
                  "<span class='sev LOW'>FAILED</span> — " + _esc(fr.get("note")))
        sections.append(f"""
<div class='lead'>
<h4>{_FRIENDLY.get(r['kind'], r['kind'])}: <code>{_esc(r['value'])}</code></h4>
<p><b>Found in:</b> {_esc('; '.join(r['found_in']))}</p>
<p>{_esc(r['why'])}</p>
<p><b>Follow-up search:</b> <code>{_esc(r['query'])}</code><br>
{status}
{'<br><span class=vec>guide: ' + _esc(fr.get('guide_path')) + '</span>'
 if fr and fr.get('guide_path') else ''}</p>
</div>""")
    total = len(ranked)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>
Follow-Up Leads — {subject}</title><style>{_CSS}</style></head><body>
<div class="cover">{_BANNER_SVG}</div>
<h1>Follow-Up Leads — {subject}</h1>
<p class="meta">{_esc(now)} · Appendix to engagement "{subject}" ·
{total} ranked lead{'s' if total != 1 else ''}</p>

<h2><span class='num'>01</span>What this appendix is</h2>
<p>During the engagement the capture passes recovered identifiers beyond the
findings scored in the main report. This appendix lists each one, where it was
found, why a stranger could use it, and the exact follow-up search that turns
it into evidence. Nothing here is a vulnerability by itself — these are the
threads the next investigation session should pull.</p>

<h2><span class='num'>02</span>Leads and follow-up searches</h2>
{''.join(sections)}

<h2><span class='num'>03</span>How to work this list</h2>
<p>Start with the leads confirmed in the most places (they repeat across
several captures), fire the listed search, and read the produced guide file.
Anything the search confirms graduates into a finding card in the main
assessment; anything unresolved stays a lead. Re-run this appendix after new
captures — it regenerates and adds the newly found identifiers.</p>

<div class='colophon'>Generated by Greypentest · lead expansion · leads mined
verbatim from this assessment's store · {_esc(now)}</div>
</body></html>"""


def generate_appendix(assessment: str, *, ranked: list, fired: list,
                      pdf: bool = True) -> dict:
    leadset = collect(assessment)
    OUT.mkdir(parents=True, exist_ok=True)
    html_path = OUT / f"{assessment}-leads.html"
    html_path.write_text(render_html(assessment,
                                     leadset.get("leads", {}), ranked, fired))
    out = {"ok": True, "assessment": assessment, "html": str(html_path)}
    if pdf:
        pdf_path = OUT / f"{assessment}-leads.pdf"
        try:
            subprocess.run(
                ["/usr/bin/chromium", "--headless", "--no-sandbox",
                 "--disable-gpu", f"--print-to-pdf={pdf_path}", str(html_path)],
                capture_output=True, timeout=60, check=False)
            out["pdf"] = str(pdf_path) if pdf_path.exists() else None
            if not pdf_path.exists():
                out["note"] = "HTML written; PDF render produced no file"
        except Exception as e:
            out["pdf"] = None
            out["note"] = f"PDF render failed: {e}"
    return out


def expand(assessment: str, *, fire_runs: bool = True, max_queries: int = 6,
           aliases: list | None = None, pdf: bool = True) -> dict:
    r = collect(assessment, aliases)
    if not r["ok"]:
        return r
    ranked = build_queries(r["leads"], r.get("subject", ""), max_queries)
    fired = fire(ranked) if fire_runs and ranked else []
    out = {"ok": True, "assessment": assessment,
           "leads_found": r["counts"],
           "queries": [{"kind": q["kind"], "value": q["value"],
                        "query": q["query"]} for q in ranked]}
    if fired:
        out["fired"] = fired
    appx = generate_appendix(assessment, ranked=ranked, fired=fired, pdf=pdf)
    out["html"] = appx.get("html")
    out["pdf"] = appx.get("pdf")
    if appx.get("note"):
        out["note"] = appx["note"]
    return out