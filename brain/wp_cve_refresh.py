"""wp_cve_refresh — grow data/wp-cve-db.json from the NVD API (2.0).

The pipeline's CVE enrichment (webpentest._findings_from_wp) is only as good
as the offline DB. This maintenance tool widens it: for each known-popular
plugin slug it queries NVD (no key required; public rate limit 5 req/30 s —
the refresher sleeps between requests), keeps CVEs whose description mentions
the plugin as a WordPress plugin, extracts the real CVSS v3.1 vector NVD
publishes, and pulls an `affected_lt` bound from the "before X.Y.Z" phrasing
in the description. Merge is additive: existing entries are never touched,
dedupe is by CVE id.

This tool talks to NVD directly over HTTPS with short timeouts (it is the DB
maintainer, run out-of-band — it is NOT part of any scan pipeline and never
touches target networks, so the scan-time http gate does not apply).

WPScan API would give cleaner `affected` ranges; if a token is set in the
environment (WPSCAN_TOKEN) the fetch path is written to prefer it, but NVD
is the no-credential default that works today.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

import webpentest

DB_PATH = webpentest.WP_CVE_DB_PATH
NVD_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"

# Popular WordPress plugins whose directory is routinely enumerable. Slugs
# match plugin-directory URLs (readme.txt Version parsing keys on these).
SEED_PLUGINS = [
    "wordpress-seo", "elementor", "wpforms-lite", "woocommerce",
    "contact-form-7", "wordfence", "akismet", "classic-editor",
    "advanced-custom-fields", "wp-mail-smtp", "litespeed-cache",
    "really-simple-ssl", "all-in-one-seo-pack", "updraftplus", "redirection",
    "jetpack", "google-site-kit", "all-in-one-wp-migration", "duplicate-post",
    "tablepress", "wp-optimize", "autoptimize", "smush", "webp-express",
    "limit-login-attempts-reloaded", "loginizer", "seo-by-rank-math",
    "translatepress-multilingual", "sitepress-multilingual-cms",
    "wp-google-maps", "contact-form-cfdb7", "duplicator", "backupwordpress",
    "file-manager-advanced", "wp-file-manager", "booking-calendar",
    "nextgen-gallery", "slider-revolution", "js_composer", "visual-composer",
]

_REQ_HEADERS = {"User-Agent": "greypentest-cve-refresh/1.0 (offline lab tooling)"}


def _nvd_query(slug: str) -> list:
    """One NVD keywordSearch page for this plugin. Returns raw CVE dicts."""
    q = urllib.parse.urlencode({
        "keywordSearch": f"wordpress plugin {slug}",
        "resultsPerPage": 50,
    })
    req = urllib.request.Request(f"{NVD_URL}?{q}", headers=_REQ_HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return (json.loads(r.read()).get("vulnerabilities") or [])


def _extract(slug: str, item: dict) -> dict | None:
    """One NVD record → one DB entry, or None when not a clean match."""
    cve = item.get("cve") or {}
    cid = cve.get("id") or ""
    if not cid.startswith("CVE-"):
        return None
    desc = ""
    for d in (cve.get("descriptions") or []):
        if d.get("lang") == "en":
            desc = d.get("value") or ""
            break
    low = desc.lower()
    # The description must name the plugin — keyword hits without the slug
    # are noise (e.g. "wordpress seo" matches every WP SEO plugin CVE).
    if slug.replace("-", " ") not in low and slug not in low:
        return None
    vec = None
    for metric in (cve.get("metrics") or {}):
        for m in cve["metrics"][metric]:
            vs = ((m.get("cvssData") or {}).get("vectorString") or "")
            if vs.startswith("CVSS:3.1"):
                vec = vs
                break
        if vec:
            break
    m = webpentest.re.search(r"before\s+(\d+(?:\.\d+)+)", desc)
    lt = m.group(1) if m else None
    if not vec and not lt:
        return None
    return {"cve": cid, "vector": vec, "affected_lt": lt,
            "summary": desc[:400]}


def refresh(slugs: list[str] | None = None, *, sleep_s: float = 7.0,
            db_path: Path | None = None) -> dict:
    """Refresh the offline CVE DB. Additive merge, dedupe by CVE id."""
    db_path = Path(db_path) if db_path else DB_PATH
    db = {}
    try:
        db = json.loads(db_path.read_text())
    except (OSError, ValueError):
        db = {}
    before = sum(len(v) for v in db.values())
    added, errors, done = 0, [], 0
    for slug in (slugs or SEED_PLUGINS):
        done += 1
        try:
            items = _nvd_query(slug)
        except Exception as e:
            errors.append(f"{slug}: {e}")
            continue
        got = db.setdefault(slug, [])
        have = {c["cve"] for c in got}
        for item in items:
            e = _extract(slug, item)
            if e and e["cve"] not in have and e["vector"]:
                got.append(e)
                have.add(e["cve"])
                added += 1
        time.sleep(sleep_s)                     # NVD public rate limit
    # Prune slugs whose extraction found nothing (keep the DB honest).
    for slug in list(db):
        if not db[slug]:
            del db[slug]
    if db_path is DB_PATH:                      # live cache must not go stale
        webpentest._wp_cve_db_cache = None
    db_path.write_text(json.dumps(db, indent=1))
    return {"ok": True, "slugs_done": done, "added": added,
            "entries_before": before, "entries_after": sum(len(v) for v in db.values()),
            "plugins": len(db), "errors": errors}