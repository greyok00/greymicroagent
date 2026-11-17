"""OSINT v2 lanes — keyless endpoint set from the OSINT Framework (arf.json,
downloaded 2026-10-30) + owner requirement: no dependence on legacy preinstalled
scanners, and no endpoint that did not answer a live probe.

Every lane was probed live before inclusion:
  crt.sh              → 200 JSON cert transparency   (domain)
  api.github.com      → 200 JSON user events         (username)
  api.gitlab.com      → 200 JSON user candidates     (username)
  keybase.io lookup   → 200 JSON user lookup         (username)
  bing imgurl scrape  → 200, 103 mediaurl hits       (reverse image)
  SearXNG :8888 with engines=bing,duckduckgo,brave,mojeek → 10+ results,
     categories=images also works                      (search + dorks)
Proactively EXCLUDED after probing (silently dead or key-walled):
  emailrep.io (unauth API disabled), saucenao (Cloudflare),
  hudsonrock check-email (empty responses), Proton PKI (returns keys for
  nonexistent addresses — false positives), HIBP (needs key).
holehe is REMOVED policy-side and denied by exec_gate.
"""
from __future__ import annotations

import json
import re
import urllib.parse

import http_safe

SEARXNG = "http://127.0.0.1:8888/search"
_ENGINES = "bing,duckduckgo,brave,mojeek"
_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126 Safari/537.36")

# --- search ----------------------------------------------------------------- #
def _searx_fetch(path_qs: str) -> bytes:
    """Loopback relay only: the local SearXNG is TRUSTED INFRA, not egress —
    host is pinned to the literal 127.0.0.1 and the port to 8888, so it can
    never fetch anything else. (2026-10-31: hardening makes loopback a
    never-net through http_safe by design.)"""
    assert SEARXNG.startswith("http://127.0.0.1:8888/")
    import urllib.request as ur
    req = ur.Request(SEARXNG + path_qs, headers={"User-Agent": _UA})
    with ur.urlopen(req, timeout=20) as resp:
        return resp.read(2_000_000)


def search(query: str, *, limit: int = 10, images: bool = False) -> dict:
    """Local SearXNG burst on the engines that actually answer. When the
    instance soft-bans (0 results although the query is plainly searchable),
    fall back to a direct Bing scrape — a different site, never a dead lane."""
    def _searx():
        q = urllib.parse.urlencode(
            {"q": query, "format": "json", "language": "en",
             "categories": "images" if images else "general",
             "engines": _ENGINES})
        body = _searx_fetch("?" + q).decode(errors="replace")
        try:
            return json.loads(body or "{}"), {}
        except ValueError:
            return {}, {}
    data, r = _searx()
    rows = data.get("results") or []
    via = "searxng"
    if not rows and not images:
        data, r = _bing_web(query)
        rows = data
        via = "bing-direct" if data else "none-available"
    out = []
    for res in rows[:max(1, limit)]:
        row = {"title": (res.get("title") or "")[:160],
               "url": res.get("url") or ""}
        if images:
            row["image_url"] = res.get("img_src") or ""
        else:
            row["snippet"] = (res.get("content") or "")[:220]
        out.append(row)
    return {"ok": True, "query": query, "images": images, "via": via,
            "count": len(out), "results": out}


def _bing_web(query: str, *, limit: int = 12) -> tuple[list, dict]:
    """Direct Bing scrape fallback (verified 2026-10-31: real results while
    the SearXNG instance soft-banned). Returns plain result rows."""
    url = "https://www.bing.com/search?" + urllib.parse.urlencode(
        {"q": query, "count": limit})
    r = http_safe.fetch(url, timeout=20, headers={"User-Agent": _UA})
    html_text = r.get("body") or ""
    out = []
    for block in re.findall(r'<li class="b_algo".*?</li>', html_text, re.S)[:limit]:
        m = re.search(r'<h2[^>]*><a [^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not m:
            continue
        href = m.group(1)
        href = href.replace("&amp;", "&")
        u = urllib.parse.parse_qs(urllib.parse.urlsplit(href).query).get("u", [""])[0]
        # Bing wraps real URLs in a tracker: u=a1<base64> (or bare <base64>)
        b64 = u[2:] if u.startswith("a1") and "aHR0" in u[:8] else \
            (u if u.startswith("aHR0") else "")
        if b64:
            import base64
            try:
                href = base64.b64decode(b64 + "===").decode(errors="replace")
            except Exception:
                pass
        title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        snip = ""
        sm = re.search(r'<p[^>]*>(.*?)</p>', block, re.S)
        if sm:
            snip = re.sub(r"<[^>]+>", "", sm.group(1)).strip()
        out.append({"url": href, "title": title, "content": snip})
    return out, r


# --- dorks ------------------------------------------------------------------ #
_DORKS = {
    "person": [
        '"{s}" site:pastebin.com', '"{s}" site:ghostbin.com', '"{s}" site:gist.github.com',
        '"{s}" (resume OR cv OR bio) filetype:pdf', '"{s}" site:linkedin.com',
        '"{s}" site:facebook.com', '"{s}" site:instagram.com',
        '"{s}" site:x.com OR site:twitter.com', '"{s}" site:github.com',
        '"{s}" (breach OR dump OR credentials) -site:pinterest.com',
        '"{s}" site:archive.org OR site:web.archive.org',
    ],
    "email": [
        '"{s}"', '"{s}" (breach OR paste OR dump OR leaked)',
        '"{s}" site:pastebin.com', '"{s}" -site:pinterest.com -site:flickr.com',
    ],
    "username": [
        '"{s}" site:github.com', '"{s}" site:pastebin.com',
        '"{s}" (profile OR account)', '"{s}" site:reddit.com',
    ],
    "domain": [
        'site:{s}', 'site:{s} filetype:pdf OR filetype:xlsx OR filetype:doc',
        'site:{s} inurl:admin OR inurl:login OR inurl:dashboard',
        '"{s}" (confidential OR internal OR password)',
        'site:pastebin.com "{s}"',
    ],
    "phone": ['"{s}"', '"{s}" (whois OR owner OR carrier OR spam)'],
}


def dorks(subject: str, kind: str = "person", *, limit: int = 5,
          run: bool = True) -> dict:
    """Deterministic Google-style dork set run through the working engines."""
    subject = (subject or "").strip()
    dork_set = _DORKS.get(kind, _DORKS["person"])
    queries = [d.format(s=subject.replace('"', "")) for d in dork_set]
    if not run:
        return {"ok": True, "queries": queries, "run": False}
    out = []
    for q in queries:
        r = search(q, limit=max(3, limit))
        out.append({"dork": q, "count": r["count"], "results": r["results"][:limit]})
    return {"ok": True, "kind": kind, "queries_run": len(out),
            "dorks": out}


# --- certificate transparency (domain) --------------------------------------- #
def crtsh(domain: str, *, limit: int = 40) -> dict:
    url = f"https://crt.sh/?q={urllib.parse.quote(domain)}&output=json"
    r = http_safe.fetch(url, timeout=30)
    try:
        rows = json.loads(r.get("body") or "[]")
    except ValueError:
        rows = []
    names = {}
    for row in rows[:400]:
        for n in (row.get("name_value") or "").split("\n"):
            n = n.strip().lower().lstrip("*.")
            if n and n.endswith(domain.lower()):
                names[n] = names.get(n, 0) + 1
    # newest entries first (crt.sh rows arrive reverse-chronologically)
    subs = list(names)[:limit]
    return {"ok": True, "tool": "crt.sh", "domain": domain,
            "certs_seen": len(rows), "subdomains": subs}


# --- identity platforms (username) ------------------------------------------- #
def identity_lanes(handle: str) -> dict:
    h = urllib.parse.quote(handle.strip(), safe="")
    lanes = []
    # GitHub — public profile + latest activity
    r = http_safe.fetch(f"https://api.github.com/users/{h}/events/public?per_page=30",
                        timeout=15, headers={"User-Agent": _UA, "Accept": "application/vnd.github+json"})
    try:
        events = json.loads(r.get("body") or "[]")
        exists = isinstance(events, list)
        recent = []
        for ev in (events if exists else [])[:8]:
            recent.append({"type": ev.get("type"), "repo": ev.get("repo", {}).get("name"),
                           "when": (ev.get("created_at") or "")[:10]})
        lanes.append({"platform": "github", "exists": exists,
                      "note": "" if exists else "no public events (may still hold a private-only account)",
                      "recent": recent})
    except (ValueError, TypeError):
        lanes.append({"platform": "github", "exists": None, "note": "unreadable"})
    # GitLab — user search returns only real matches; a 4xx/5xx body is an
    # error OBJECT (true-y dict), so "exists" must demand a real LIST (audit
    # 2026-10-31: GitLab errors were read as "account exists")
    r = http_safe.fetch(f"https://gitlab.com/api/v4/users?username={h}", timeout=15,
                        headers={"User-Agent": _UA})
    try:
        rows = json.loads(r.get("body") or "[]")
        ok_rows = isinstance(rows, list)
        lanes.append({"platform": "gitlab",
                      "exists": bool(ok_rows and rows),
                      "note": "" if ok_rows else
                      f"gitlab error (status {r.get('status')})",
                      "profiles": [f"https://gitlab.com/{g.get('username')}"
                                   for g in (rows[:3] if ok_rows else [])
                                   if isinstance(g, dict)]})
    except (ValueError, TypeError):
        lanes.append({"platform": "gitlab", "exists": None, "note": "unreadable"})
    # Keybase — explicit status code from their API
    r = http_safe.fetch(f"https://keybase.io/_/api/1.0/user/lookup.json?username={h}",
                        timeout=15, headers={"User-Agent": _UA})
    try:
        data = json.loads(r.get("body") or "{}")
        status = (data.get("status") or {}).get("code")
        them = data.get("them")
        lanes.append({"platform": "keybase",
                      "exists": bool(them) and them != "null",
                      "note": (data.get("status") or {}).get("desc", "")})
    except (ValueError, TypeError):
        lanes.append({"platform": "keybase", "exists": None, "note": "unreadable"})
    return {"ok": True, "tool": "identity_lanes", "handle": handle,
            "lanes": lanes}


# --- reverse image (Bing imgurl keyless scrape) ------------------------------- #
_MEDIAURL_RE = re.compile(r"murl&quot;:&quot;([^&]+)&quot;|murl\":\"([^\"]+)\"")


def reverse_image(image_url: str, *, limit: int = 10) -> dict:
    """Bing imgurl reverse-image search: keyless, verified 200 with hits."""
    q = "imgurl:" + urllib.parse.quote(image_url, safe="")
    url = ("https://www.bing.com/images/search?" +
           urllib.parse.urlencode({"q": q}))
    r = http_safe.fetch(url, timeout=20, headers={"User-Agent": _UA})
    text = (r.get("body") or "").replace("\\u0026", "&")
    found, seen = [], set()
    for m in _MEDIAURL_RE.findall(text):
        src = (m[0] or m[1]).replace("\\/", "/")
        if src and src not in seen:
            seen.add(src)
            found.append(src)
        if len(found) >= limit:
            break
    # companion searches on every engine that matters (operator-clickable)
    enc = urllib.parse.quote(image_url, safe="")
    links = {
        "google_lens": f"https://lens.google.com/uploadbyurl?url={enc}",
        "yandex": f"https://yandex.com/images/search?rpt=imageview&url={enc}",
        "tineye": f"https://tineye.com/search?url={enc}",
        "saucenao": f"https://saucenao.com/search.php?url={enc}",
    }
    return {"ok": True, "tool": "bing-reverse-image", "image": image_url,
            "matches_found": len(found), "matches": found,
            "manual_searches": links,
            "note": "google_lens link opens in a browser tab"}


# --- WhatsMyName (username → candidate profile URLs) -------------------------- #
def whatsmyname(handle: str, *, limit: int = 60) -> dict:
    """WebBreacher/WhatsMyName dataset (692 site templates, live-verified
    2026-10-31 — osint-industries mirror is 404, use WebBreacher main).
    PASSIVE by design: substitutes the handle into each site's profile-URL
    template and returns candidates grouped by category. Per-site HTTP checks
    are NOT fired (would need ~690 allowlisted hosts — against stealth mode);
    the agent/operator verifies interesting candidates or runs maigret/blackbird
    for the active sweep."""
    url = ("https://raw.githubusercontent.com/WebBreacher/WhatsMyName/"
           "main/wmn-data.json")
    r = http_safe.fetch(url, timeout=30, headers={"User-Agent": _UA})
    try:
        data = json.loads(r.get("body") or "{}")
    except ValueError:
        return {"ok": False, "tool": "whatsmyname", "error": "dataset fetch failed"}
    out, cats = [], {}
    for site in data.get("sites", []):
        tpl = site.get("uri_check") or ""
        if "{" + "account" + "}" not in tpl:
            continue
        u = tpl.replace("{account}", urllib.parse.quote(handle, safe=""))
        cat = site.get("cat") or "other"
        cats[cat] = cats.get(cat, 0) + 1
        if len(out) < limit:
            out.append({"site": site.get("name"), "url": u, "category": cat})
    return {"ok": True, "tool": "whatsmyname", "handle": handle,
            "sites_in_dataset": len(data.get("sites", [])),
            "candidates": out,
            "categories": dict(sorted(cats.items(), key=lambda x: -x[1])),
            "note": f"first {limit} candidates shown — full set spans "
                    f"{len(data.get('sites', []))} sites; verify by visiting or "
                    "via maigret/blackbird active sweeps"}


# --- email permutations ------------------------------------------------------- #
def permutate(name: str, domain: str = "gmail.com", *, limit: int = 12) -> dict:
    parts = [p for p in re.split(r"\s+", (name or "").strip().lower()) if p]
    if len(parts) < 2:
        return {"ok": False, "error": "need first+last name to permute"}
    f, l = parts[0], parts[-1]
    shapes = [f"{f}.{l}", f"{f}{l}", f"{l}.{f}", f"{f[0]}{l}", f"{f}_{l}",
              f"{f[0]}.{l}", f"{f}.{l[0]}", f"{l}{f[0]}", f"{f}{l[0]}",
              f"{f}-{l}"]
    out = [f"{s}@{domain}" for s in shapes][:limit]
    return {"ok": True, "name": name, "domain": domain, "candidates": out,
            "note": "candidate addresses only — verify each with the "
                    "operator or a public source BEFORE citing; never guess "
                    "one of these as a fact in a finding"}


# --- phone parsing ------------------------------------------------------------ #
def phone_info(number: str, region: str = "US") -> dict:
    try:
        import phonenumbers as pn
        from phonenumbers import geocoder, carrier, timezone as pntz
    except ImportError:
        return {"ok": False, "error": "phonenumbers lib not installed"}
    try:
        z = pn.parse(number, region)
    except pn.NumberParseException as e:
        return {"ok": False, "error": f"unparseable: {e}"}
    if not pn.is_valid_number(z):
        return {"ok": False, "number": number, "valid": False}
    # values ground-truthed against the installed lib (2026-10-31): the old
    # table was shifted one-off (mobile was labelled "fixed-line-or-mobile",
    # toll-free "pager")
    _TYPES = {0: "fixed-line", 1: "mobile", 2: "fixed-line-or-mobile",
              3: "toll-free", 4: "premium-rate", 5: "shared-cost",
              6: "voip", 7: "personal-number", 8: "pager",
              9: "uan", 97: "voicemail"}
    return {"ok": True, "valid": True, "number": pn.format_number(
        z, pn.PhoneNumberFormat.E164),
        "region": geocoder.description_for_number(z, "en") or "",
        "carrier": carrier.name_for_number(z, "en") or "unknown",
        "tz": pntz.time_zones_for_number(z)[:2],
        "type": _TYPES.get(pn.number_type(z), "other")}