"""Scope handoff — the single wrap-up checkpoint for every suite (owner rule
2026-10-31): when a suite discovers assets OUTSIDE its own scope (a person run
finding randybarham.com, a web run finding device IPs, a person name in a web
recon), it NEVER acts on them. It collects everything first, then presents ONE
consolidated list — candidate → which wrapper would test it → why it was
found — and asks the operator to pick. The entire plan, all candidates back to
back, before any first scan.

The person slice physically blocks scan/webpentest tools already; this module
makes the ask-step deterministic instead of prompt-dependent.
"""
from __future__ import annotations

import re

import store

# suite that produced the assessment → what is IN scope there
_HOST_RE = re.compile(
    r"\b((?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+)\b",
    re.I)
_IPV4_RE = re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b")
_URL_RE = re.compile(r"https?://[^\s\"'<>)]+", re.I)
_HANDLE_RE = re.compile(r"(?:^|\s|@)([A-Za-z0-9_.]{3,20})(?:$|\s|,)")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

_NON_DOMAIN_PARTS = ("example.", "test.", "dryrun", "lab.local", "localhost",
                     "invalid.", "127.0.0.1", "0.0.0.0", "dry.", "greypentest")
_SUGGEST = {"web": "webtest", "network": "networktest",
            "devices": "devicetest", "person": "personstest"}


def _in_scope(suite: str, kind: str, value: str) -> bool:
    if suite == "web":
        return kind in ("domain", "url")
    if suite == "network":
        return kind in ("ip", "domain")          # hosts legitimately probed
    if suite == "devices":
        return kind in ("device", "ip")          # fingerprints + live addrs
    return False                                  # person: nothing is in scope


def _classify(v: str) -> str:
    if _URL_RE.match(v):
        return "url"
    if _IPV4_RE.fullmatch(v):
        return "ip"
    if _EMAIL_RE.fullmatch(v):
        return "email"
    if v and "." in v and " " not in v and "@" not in v:
        return "domain"
    if " " in v:
        return "person"
    if _HANDLE_RE.fullmatch(v.strip()):
        return "handle"
    return "unknown"


def _collect_values(rows, fields) -> list:
    out = []
    for r in rows:
        blob = " ".join(str(r.get(f) or "") for f in fields)
        blob += " " + str(r.get("details") or r.get("detail") or "")
        for m in _URL_RE.findall(blob):
            out.append((m.rstrip(".,)"), "url"))
        # remove URLs/emails BEFORE host extraction so an address's host-part
        # (r@x.io → "x.io") and tracked URLs never surface as free-standing
        # domains, and dotted quads are IPs (one kind, not "domain" too)
        blob = _URL_RE.sub(" ", blob)
        emails = _EMAIL_RE.findall(blob)
        for m in emails:
            out.append((m, "email"))
        blob = _EMAIL_RE.sub(" ", blob)
        for m in _IPV4_RE.findall(blob):
            out.append((m, "ip"))
        for m in _HOST_RE.findall(blob):
            if _IPV4_RE.fullmatch(m):
                continue
            out.append((m, "domain"))
        # bare single words from titles/name are often handles
        name = str(r.get("name") or r.get("title") or "").strip()
        if name and " " not in name and not _IPV4_RE.fullmatch(name) \
                and "." not in name and 2 < len(name) < 20:
            out.append((name, "handle"))
    return out


def collect(assessment: str, suite: str = "person") -> dict:
    """Everything the assessment recorded, split into in-scope items (this
    suite keeps them) and out-of-scope candidates (the ask list)."""
    a = store.load_assessment(assessment)
    if not a.get("ok"):
        return {"ok": False, "error": f"assessment '{assessment}' not found"}
    cards = store.list_cards(assessment)
    recon = store.list_recon(assessment)
    seen, items = {}, {}
    for v, kind in _collect_values(recon, ["type", "name"]) \
            + _collect_values(cards, ["type", "title"]):
        v = v.strip().rstrip(".,;")
        low = v.lower()
        if not v or any(p in low for p in _NON_DOMAIN_PARTS):
            continue
        # 2026-10-31 QA (GT-39): scanner timing/latency values ('0.26s',
        # '7.95', '402.51') used to ride into domain candidate lists — a value
        # made only of digits/dots/commas + optional trailing unit is not a
        # hostname, so drop it before it pollutes the ask list.
        if re.fullmatch(r"\d[\d.,]*(?:ms|s)?", v, re.I):
            continue
        key = kind + ":" + v.lower()
        # a URL whose host already stands as a domain candidate merges into it
        if kind == "url":
            _m = re.match(r"https?://([^/:]+)", v, re.I)
            if _m and "domain:" + _m.group(1).lower() in seen:
                seen["domain:" + _m.group(1).lower()] += 1
                continue
        if key in seen:
            seen[key] += 1
            continue
        seen[key] = 1
        items[key] = {"value": v[:120], "kind": kind}

    candidates, in_scope = [], []
    for key, it in items.items():
        kind = it["kind"]
        if _in_scope(suite, kind, it["value"]):
            in_scope.append(it)
            continue
        # post-merge: a URL already represented by its host as a domain
        if kind == "url":
            _m = re.match(r"https?://([^/:]+)", it["value"], re.I)
            if _m and "domain:" + _m.group(1).lower() in items:
                seen["domain:" + _m.group(1).lower()] += seen[key]
                continue
        want = {"domain": "webtest", "url": "webtest", "ip": "networktest",
                "handle": None, "email": None, "person": None,
                "unknown": None}[kind]
        candidates.append({**it, "sources": seen[key],
                           "suggested": want})
    # device-looking rows (adb/serial/imei/OS recon types) suggest devicetest
    for r in recon + cards:
        t = (str(r.get("type") or "") + str(r.get("name") or "")).lower()
        if any(w in t for w in ("adb", "device", "android", "ios", "imei",
                                "serial", "firmware")):
            v = (r.get("details") or {}).get("value") or r.get("name") or ""
            if v and not any(c["value"] == v for c in candidates):
                candidates.append({"value": str(v)[:120], "kind": "device",
                                   "sources": 1, "suggested": "devicetest"})
    candidates.sort(key=lambda c: (-c["sources"], c["kind"], c["value"]))
    return {"ok": True, "assessment": assessment, "suite": suite,
            "in_scope_count": len(in_scope),
            "out_of_scope": candidates,
            "candidates": candidates}


def present(collected: dict) -> dict:
    """Turn the collected candidate list into the ONE combined ask paragraph —
    complete plan, all candidates together, no action taken."""
    cands = collected.get("candidates") or []
    suite = collected.get("suite", "person")
    if not cands:
        return {"ok": True, "ask_text":
                "Nothing outside this assessment's scope was recorded, so no "
                "follow-up options to confirm. Ready to continue with the "
                "report unless you want to add targets."}
    lines = []
    for c in cands:
        s = c.get("suggested")
        tail = f" — could be tested by {s}" if s else \
            " — no automated suite applies; manual review only"
        lines.append(f"  • {c['value']} ({c['kind']}"
                     + (f", seen {c['sources']}×" if c["sources"] > 1 else "")
                     + f"){tail}")
    ask = (f"Wrap-up options found during this {suite} assessment — listed "
           "ALL together before acting on any of them. Nothing has been "
           "scanned yet. Which of these do you want to continue with?\n"
           + "\n".join(lines) +
           "\nPick any, all, or none — I will not start the first one until "
           f"you say so{'' if suite == 'person' else ''}.")
    return {"ok": True, "ask_text": ask, "count": len(cands)}


def handoff(assessment: str, suite: str = "person") -> dict:
    """Tool entry: collect from the store, return + render the ask text."""
    c = collect(assessment, suite)
    if not c.get("ok"):
        return c
    p = present(c)
    return {**c, "ask_text": p.get("ask_text", ""),
            "ask_count": p.get("count", 0)}