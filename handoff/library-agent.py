#!/usr/bin/env python3
"""
library-agent.py — autonomous handoff driver for the research-library audit.

Runs a LOCAL ollama model (target: 3.5B class, e.g. qwen3.5:3.5b) as the brain,
but the script owns everything the small model can't be trusted with:

  - work queue in owner-mandated REVERSE order (legal -> finance -> osint-pi
    -> cybersecurity; within each group, pages walked BACKWARDS)
  - deterministic per-page facts: NSCE section presence, word count, image
    count, foreign-script detection, breadcrumb link resolution
  - edit guards: append-only inserts before a fixed anchor, plus
    exact-unique-match removals only; .bak written before every write
  - resumable state.json — crash-safe, indefinite, re-run anytime
  - research: SearXNG instance at http://127.0.0.1:8890 (local, no cloud)

Protocol: ONE JSON object per model turn (see AGENT-PROMPT.md):
  {"action":"search","query":"..."}
  {"action":"fetch","url":"..."}
  {"action":"append_section","html":"<div class=\"full\">...</div>"}
  {"action":"remove_html","exact":"...exact substring present exactly once..."}
  {"action":"note","text":"finding for the ledger"}
  {"action":"complete","summary":"what was done"}
  {"action":"blocked","reason":"why this page cannot proceed"}

Usage:
  python3 handoff/library-agent.py                  # run the whole queue, forever-ready
  python3 handoff/library-agent.py --page legal/civil-procedure/fed-rule.html
  python3 handoff/library-agent.py --model qwen3.5:3.5b --max-pages 3
  python3 handoff/library-agent.py --dry-run        # show queue + facts, no model calls
"""

import argparse, json, os, re, shutil, subprocess, sys, time, urllib.request
from pathlib import Path

ROOT = Path.home() / "grey" / "research-libary"   # greymicroagent fork: the REAL library is ~/grey/research-libary (HOME is /home/grey, project dir is grey)
HANDOFF = ROOT / "handoff"
STATE = HANDOFF / "state.json"
LEDGER = HANDOFF / "ledger.md"
ANCHOR = '<div class="full"><nav class="pn">'
PROMPT_FILE = HANDOFF / "AGENT-PROMPT.md"
SEARX = "http://127.0.0.1:8890"
OLLAMA = os.environ.get("OLLAMA_HOST", "127.0.0.1:11600")
if "://" not in OLLAMA:
    OLLAMA = "http://" + OLLAMA                                  # ollama-style host:port

GROUPS = ["legal", "finance", "osint-pi", "cybersecurity"]   # reverse-order walk

# ---------------------------------------------------------------- state ----

def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"pages": {}}

def save_state(st):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1))
    tmp.replace(STATE)

def log(note):
    stamp = time.strftime("%Y-%m-%d %H:%M")
    with LEDGER.open("a") as f:
        f.write(f"- {stamp} {note}\n")

# ---------------------------------------------------------------- queue ----

def rel_html(page):
    rel = str(page.relative_to(ROOT))
    return rel

def build_queue():
    pages = []
    for grp in GROUPS:
        got = sorted(p for p in (ROOT / grp).rglob("*.html"))
        pages += got[::-1]                              # BACKWARDS within group
    return [rel_html(p) for p in pages]

# ------------------------------------------------------- deterministic ----

FOREIGN_RANGES = [
    (0x0400, 0x04FF, "Cyrillic"), (0x0600, 0x06FF, "Arabic"),
    (0x4E00, 0x9FFF, "CJK"), (0x0900, 0x097F, "Devanagari"),
    (0x0E00, 0x0E7F, "Thai"), (0xAC00, 0xD7AF, "Hangul"),
]

def foreign_scripts(text):
    found = {}
    for lo, hi, name in FOREIGN_RANGES:
        n = sum(1 for c in text if lo <= ord(c) <= hi)
        if n > 3:
            found[name] = n
    return found

def breadcrumb_ok(html, rel):
    """Check the footer breadcrumb links resolve to real files."""
    bad = []
    for href in re.findall(r'<a href="(\.\./[^"]+)">', html):
        if "http" in href:
            continue
        target = (ROOT / rel).parent
        for part in href.split("/"):
            if part == "..":
                target = target.parent
            elif part:
                target = target / part
        if not target.exists():
            bad.append(href)
    return bad

def page_facts(rel):
    p = ROOT / rel
    html = p.read_text(errors="replace")
    body = html.lower()
    # hub/index pages (no append anchor) are exempt from the word/image gates
    is_hub = ANCHOR not in html
    facts = {
        "file": rel,
        "bytes": len(html),
        "words": len(re.sub(r"<[^>]+>", " ", html).split()),
        "images": html.count("<img"),
        "tables": body.count("<table"),
        "code_blocks": body.count("<pre"),
        "has_sources": "class=\"sources\"" in body,
        "has_nation_state": bool(re.search(r"nation[\s-]*state", body)),
        "has_crime_economy": bool(re.search(r"crime[\s-]*economy", body)),
        "foreign_scripts": foreign_scripts(html),
        "broken_breadcrumb_links": breadcrumb_ok(html, rel),
        "duplicate_imgs": [u for u in re.findall(r'<img[^>]*src="([^"]+)"', html)
                           if html.count(f'src="{u}"') > 1],
    }
    if ANCHOR not in html:
        facts["hub_page"] = True
    return facts

def needs_work(f):
    if f.get("hub_page"):
        return bool(f["foreign_scripts"] or f["broken_breadcrumb_links"]
                    or f["duplicate_imgs"])          # hubs: only hard defects
    return (not f["has_nation_state"] or not f["has_crime_economy"]
            or f["words"] < 1200 or f["foreign_scripts"]
            or f["broken_breadcrumb_links"] or f["duplicate_imgs"]
            or not f["images"] or not f["has_sources"])
# ---------------------------------------------------------------- tools ----

def searx_search(query, k=6):
    url = f"{SEARX}/search?q={urllib.parse.quote(query)}&format=json"
    try:
        data = json.loads(urllib.request.urlopen(url, timeout=20).read())
        return [{"title": r["title"], "url": r["url"], "snippet": r["content"]}
                for r in data.get("results", [])[:k]]
    except Exception as e:
        return [{"error": str(e)}]

def fetch_url(url, limit=6000):
    if not url.startswith("http"):
        return {"error": "absolute http(s) url required"}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 library-agent"})
        text = urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "replace")
        text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return {"url": url, "text": text[:limit]}
    except Exception as e:
        return {"error": str(e)}

def guard_html(html_frag, rel, state):
    """Append-only guard: fragment must be a full block, open+closed div,
    cite sources inline, and not contain page-shell tokens."""
    if not html_frag.strip().startswith("<div"):
        return "edit must start with <div"
    if html_frag.count("<div") != html_frag.count("</div>"):
        return "unbalanced <div> tags"
    for bad in ("</body>", "</html>", "<!DOCTYPE", "<head", 'class="pn"',
                "placeholder", "lorem", "TODO", "dummy", "example.com/"):
        if bad.lower() in html_frag.lower():
            return f"forbidden token: {bad}"
    if "http" not in html_frag:
        return "section must cite at least one real source URL"
    st = state["pages"][rel]
    for prev in st.get("appended", []):
        if html_frag.strip() == prev.strip():
            return "duplicate of a section already appended to this page"
    return None

def apply_edit(rel, html_frag, exact_removal):
    p = ROOT / rel
    html = p.read_text()
    shutil.copy2(p, p.with_suffix(".html.bak"))
    if exact_removal:
        if html.count(exact_removal) != 1:
            return None, "removal string must appear EXACTLY once in the page"
        html = html.replace(exact_removal, "")
    if html_frag:
        if ANCHOR not in html:
            return None, "append anchor missing"
        html = html.replace(ANCHOR, html_frag.strip() + "\n" + ANCHOR, 1)
    p.write_text(html)
    return True, None

# ---------------------------------------------------------------- model ----

def ollama_chat(model, system, messages, num_predict=768):
    payload = {"model": model, "messages": [{"role": "system", "content": system}] + messages,
               "stream": False, "think": False,
               "options": {"num_predict": num_predict, "temperature": 0.2}}
    req = urllib.request.Request(f"{OLLAMA}/api/chat",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    out = json.loads(urllib.request.urlopen(req, timeout=300).read())
    return out["message"]["content"]

def parse_action(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        a = json.loads(m.group(0))
        return a if isinstance(a, dict) and "action" in a else None
    except json.JSONDecodeError:
        return None

# ---------------------------------------------------------------- loop ----

def run_page(rel, model, system, max_turns, dry):
    st = load_state()
    ent = st["pages"].setdefault(rel, {"status": "pending", "findings": [], "appended": []})
    facts = page_facts(rel)
    if dry:
        print(json.dumps(facts, indent=1))
        return
    status = ent.get("status", "pending")
    if status == "done":
        print(f"[skip] {rel} done")
        return
    if status != "in-progress":
        ent["status"] = "in-progress"
        save_state(st)
        log(f"START {rel} facts: ns={facts['has_nation_state']} ce={facts['has_crime_economy']} "
            f"words={facts['words']} imgs={facts['images']} foreign={facts['foreign_scripts']} "
            f"brokenlinks={facts['broken_breadcrumb_links']} dupimgs={len(facts['duplicate_imgs'])}")

    html = (ROOT / rel).read_text(errors="replace")
    visible = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
    visible = re.sub(r"[ \t]+", " ", visible)
    messages = [{"role": "user", "content":
        f"AUDIT TASK for page: {rel}\nDETERMINISTIC FACTS (trust these, they are machine-checked):\n"
        + json.dumps(facts, indent=1)
        + f"\n\nPAGE TEXT (may be truncated):\n{visible[:12000]}\n\n"
        + "Reply with exactly ONE json action object. Fix one thing per turn."}]
    last_verdict = {"ok": None}

    for turn in range(1, max_turns + 1):
        try:
            raw = ollama_chat(model, system, messages)
        except Exception as e:
            log(f"MODEL-ERROR {rel}: {e}")
            print(f"[model-error] {rel}: {e}")
            return
        act = parse_action(raw)
        if act is None:
            messages.append({"role": "assistant", "content": raw[:500]})
            messages.append({"role": "user", "content":
                "Invalid response. Reply with ONLY one json object from the protocol."})
            continue

        a = act["action"]; result = ""
        if a == "search":
            result = json.dumps(searx_search(act.get("query", "")))
        elif a == "fetch":
            result = json.dumps(fetch_url(act.get("url", "")))
        elif a == "append_section":
            frag = act.get("html", "")
            err = guard_html(frag, rel, st)
            if not err:
                ok, err = apply_edit(rel, frag, None)
                if ok:
                    ent["appended"].append(frag)
                    facts = page_facts(rel)          # refresh
                    result = "APPENDED OK. Updated facts: " + json.dumps(facts)
                else:
                    result = f"EDIT REJECTED: {err}"
            else:
                result = f"EDIT REJECTED: {err}"
        elif a == "remove_html":
            ok, err = apply_edit(rel, None, act.get("exact", ""))
            result = "REMOVED OK. " if ok else f"REMOVE REJECTED: {err}"
            if ok:
                facts = page_facts(rel)
                result += "Updated facts: " + json.dumps(facts)
        elif a == "note":
            text = act.get("text", "")[:300]
            ent["findings"].append(text); log(f"NOTE {rel}: {text}")
            result = "noted"
        elif a == "complete":
            f2 = page_facts(rel)
            if needs_work(f2):
                result = ("COMPLETE REJECTED — machine checks still failing: "
                          + json.dumps({k: f2[k] for k in
                            ("has_nation_state", "has_crime_economy", "words", "images",
                             "foreign_scripts", "broken_breadcrumb_links", "has_sources")}))
            else:
                ent["status"] = "done"
                ent["summary"] = act.get("summary", "")[:300]
                save_state(st)
                log(f"DONE {rel}: {ent['summary']}")
                print(f"[done] {rel}")
                return
        elif a == "blocked":
            ent["status"] = "blocked"
            ent["blocked_reason"] = act.get("reason", "")[:300]
            save_state(st); log(f"BLOCKED {rel}: {ent['blocked_reason']}")
            print(f"[blocked] {rel}")
            return
        else:
            result = "unknown action"

        if len(messages) > 16:                          # context discipline for 3.5B
            messages = messages[-2:]
        messages.append({"role": "assistant", "content": json.dumps(act)[:1200]})
        messages.append({"role": "user", "content": f"RESULT: {result[:4000]}\nNext: one json action."})
        save_state(st)

    ent["status"] = "pending"                           # turn budget spent, retry later
    save_state(st); log(f"TIMEOUT {rel} after {max_turns} turns")
    print(f"[timeout] {rel}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None)
    ap.add_argument("--page", default=None)
    ap.add_argument("--max-pages", type=int, default=0)
    ap.add_argument("--max-turns", type=int, default=24)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    model = args.model
    if not model:
        models = subprocess.run(["ollama", "list"], capture_output=True, text=True).stdout
        locals_ = [l.split()[0] for l in models.splitlines()[1:]
                   if l.strip() and ":cloud" not in l]
        model = locals_[0] if locals_ else None
    if not model and not args.dry_run:
        sys.exit("No local model found. Pull one, e.g.: ollama pull qwen3.5:3.5b "
                 "or pass --model NAME")

    queue = ([args.page] if args.page else build_queue())
    tried = 0
    for rel in queue:
        facts = page_facts(rel)
        if not args.page and load_state()["pages"].get(rel, {}).get("status") == "done" \
           and not needs_work(facts):
            continue                                             # already done
        print(f"\n=== {rel} ===")
        system = PROMPT_FILE.read_text()
        run_page(rel, model, system, args.max_turns, args.dry_run)
        tried += 1
        if args.max_pages and tried >= args.max_pages:
            break
    print(f"\npass complete — {tried} page(s) attempted this run")

if __name__ == "__main__":
    import urllib.parse
    main()