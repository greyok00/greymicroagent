import json, sys, os, re, time, importlib.util
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rag.kbcore as kb

SERVER = {"name": "rag", "version": "0.1.0"}
PROTO = "2024-11-05"
ROW_BYTES = kb.DIMS * 4
PREVIEW = 700


def _today():
    return time.strftime("%F")


def _model_state():
    files = os.path.exists(os.path.join(kb.MODEL, "onnx", "model_quantized.onnx"))
    ort = importlib.util.find_spec("onnxruntime") is not None
    tok = importlib.util.find_spec("tokenizers") is not None
    if files and ort and tok:
        return "ready (MiniLM encoder present; search runs semantic+keyword)"
    if files:
        return "model files present, python deps missing; keyword mode only"
    return "encoder not installed; keyword mode only"


def _sync_manifest(path, n):
    fp = os.path.join(str(path), "manifest.json")
    try:
        mm = json.load(open(fp, encoding="utf-8"))
    except Exception:
        return
    mm["records"] = n
    mm["built"] = time.strftime("%F %T")
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(mm, f, indent=2)


def _row_url(r):
    return r.get("url") or r.get("u") or r.get("p") or ""


def _matching(path, match):
    m = match.lower()
    out = []
    for r in kb.pack_rows(path):
        hay = " ".join(x for x in (str(r.get(k, "")) for k in ("t", "src", "url", "u", "p")) if x).lower()
        if m in hay:
            out.append(r["i"])
    return out


def _stage(path, db, match, ids):
    rows = kb.pack_rows(path)
    sample = [{"i": r["i"], "t": r["t"]} for r in rows if r["i"] in ids][:50]
    data = {"db": db, "match": match, "ids": ids, "preview": sample, "ts": time.strftime("%F %T")}
    with open(os.path.join(str(path), "pending-remove.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return data


def _staged(path, db, match):
    fp = os.path.join(str(path), "pending-remove.json")
    try:
        d = json.load(open(fp, encoding="utf-8"))
    except Exception:
        return None
    if d.get("db") != db or d.get("match") != match:
        return None
    return d.get("ids") or []


def _apply_remove(path, ids):
    rows = kb.pack_rows(path)
    ids = set(ids)
    kept = [r for r in rows if r["i"] not in ids]
    removed = len(rows) - len(kept)
    vec = "absent"
    if removed and rows:
        tmp = os.path.join(str(path), "pack.jsonl.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            for r in kept:
                f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
        os.replace(tmp, os.path.join(str(path), "pack.jsonl"))
        vec = _trim_vectors(path, len(rows), [r["i"] not in ids for r in rows])
        _sync_manifest(path, len(kept))
    return removed, vec


def _trim_vectors(path, rows_before, keep_flags):
    d = os.path.join(str(path), "learned")
    vp, ip = os.path.join(d, "vectors.bin"), os.path.join(d, "ids.jsonl")
    if not os.path.exists(vp):
        return "absent"
    size = os.path.getsize(vp)
    vec_rows = size // ROW_BYTES
    id_rows = 0
    if os.path.exists(ip):
        with open(ip, encoding="utf-8") as f:
            id_rows = sum(1 for l in f if l.strip())
    if vec_rows != rows_before or id_rows != rows_before or len(keep_flags) != rows_before:
        try:
            os.remove(ip)
        except OSError:
            pass
        os.remove(vp)
        return "cleared"
    with open(vp, "rb") as f:
        blob = f.read()
    lines = []
    with open(ip, encoding="utf-8") as f:
        lines = [l for l in f if l.strip()]
    kt = os.path.join(d, "vectors.bin.tmp")
    with open(kt, "wb") as f:
        for j, keep in enumerate(keep_flags):
            if keep:
                f.write(blob[j * ROW_BYTES:(j + 1) * ROW_BYTES])
    os.replace(kt, vp)
    it = os.path.join(d, "ids.jsonl.tmp")
    with open(it, "w", encoding="utf-8") as f:
        for j, keep in enumerate(keep_flags):
            if keep:
                f.write(lines[j])
    os.replace(it, ip)
    return "trimmed"


def tool_status(a):
    db = (a or {}).get("db")
    if db:
        path = kb.db_dir(db)
        records = len(kb.pack_rows(path))
    else:
        records = sum(x["records"] for x in kb.dbs())
    return {"db": db or "*", "records": records, "dbs": kb.dbs(), "model_state": _model_state()}


def tool_search(a):
    path = kb.db_dir(a["db"])
    hits = kb.search(path, a["query"], int(a.get("k", 5)), None)
    if not hits:
        return {"query": a["query"], "hits": 0,
                "note": "no match — not covered by this database; escalate, do not guess"}
    rows = {r["i"]: r for r in kb.pack_rows(path)}
    lines = []
    for r in hits:
        row = rows.get(r["i"], {})
        r["url"] = _row_url(row)
        r["date"] = row.get("date", "")
        lines.append(f"{r['i']} [{r['band']} cos={r['cos']}] | {r['t'][:90]} | {r['date']} | {r['src']} | {r['url']}")
        x = re.sub(r"\s+", " ", r["x"])
        lines.append(f"    {x[:PREVIEW]}{' ...' if len(x) > PREVIEW else ''}")
        lines.append("")
    return {"query": a["query"], "hits": len(hits), "text": "\n".join(lines),
            "results": [{k2: r[k2] for k2 in ("i", "t", "d", "src", "url", "date", "cos", "band")} for r in hits]}


def tool_ingest_pdf(a):
    path = kb.db_dir(a["db"])
    kb.init_db(path)
    # 2026-11-19: the TUI/wiring bridge passes a plural "paths" list while the
    # MCP caller sends "path". Accept both or every PDF ingest silently says
    # "not a readable pdf" with an empty path.
    _raw = a.get("path") or (a.get("paths") or [""])[0]
    src = os.path.expanduser(str(_raw or ""))
    if not src.lower().endswith(".pdf") or not os.path.isfile(src):
        return {"db": a["db"], "added": 0, "note": f"not a readable pdf: {src}"}
    title = os.path.splitext(os.path.basename(src))[0]
    text = kb.pdf_text(src)
    recs = kb.records_from(text, {"t": title, "src": "pdf", "url": src, "date": _today()})
    added = kb.add_records(path, recs, None, src="pdf") if recs else []
    return {"db": a["db"], "title": title, "added": len(added), "chars": len(text)}


def _page_title(raw, url):
    m = re.search(r"<title[^>]*>(.*?)</title", raw, re.I | re.S)
    if m:
        t = re.sub(r"\s+", " ", m.group(1)).strip()
        if t:
            return t[:120]
    return url


def tool_ingest_urls(a):
    path = kb.db_dir(a["db"])
    kb.init_db(path)
    urls = [u.strip() for u in (a.get("urls") or []) if str(u).strip().startswith("http")]
    out, total = [], 0
    for u in urls:
        ok, data, ctype, status = kb.fetch(u)
        if not ok:
            out.append({"url": u, "added": 0, "note": f"fetch failed: {status}"})
            continue
        raw = data.decode("utf-8", "ignore")
        route, _routable, why = kb.content_route(ctype, data)
        if route == "html":
            text = kb.html_text(raw)
        elif route == "text":
            text = raw
        else:
            out.append({"url": u, "added": 0, "note": f"skipped: {why}"})
            continue
        recs = kb.records_from(text, {"t": _page_title(raw, u), "src": "web", "url": u, "date": _today()})
        added = kb.add_records(path, recs, None, src="web") if recs else []
        total += len(added)
        out.append({"url": u, "added": len(added)})
    if not urls:
        return {"db": a["db"], "added": 0, "note": "no http urls in input", "urls": []}
    return {"db": a["db"], "added": total, "urls": out}


def tool_ingest_text(a):
    path = kb.db_dir(a["db"])
    kb.init_db(path)
    text = str(a.get("text", ""))
    title = str(a.get("title", "")).strip() or "untitled"
    if not text.strip():
        return {"db": a["db"], "title": title, "added": 0, "note": "empty text; nothing ingested"}
    base = {"t": title, "src": str(a.get("source", "") or "text"),
            "url": str(a.get("url", "") or ""), "date": str(a.get("date", "") or _today())}
    recs = kb.records_from(text, base)
    if not recs:
        return {"db": a["db"], "title": title, "added": 0,
                "note": "text below the chunk floor produced no records; nothing ingested"}
    added = kb.add_records(path, recs, None, src="text")
    if not added:
        return {"db": a["db"], "title": title, "added": 0,
                "note": "duplicate of content already in this db; nothing ingested"}
    return {"db": a["db"], "title": title, "added": len(added), "note": ""}


def tool_remove(a):
    path = kb.db_dir(a["db"])
    kb.init_db(path)
    match = str(a.get("match", ""))
    if not match:
        return {"db": a["db"], "match": match, "removed": 0,
                "note": "refused: match is empty; specify what to remove, nothing deleted"}
    if a.get("confirm") is not True:
        ids = _matching(path, match)
        data = _stage(path, a["db"], match, ids)
        return {"db": a["db"], "match": match, "removed": 0, "matched": len(ids),
                "preview": data["preview"],
                "note": "refused: nothing deleted; pass confirm: true (the boolean true) to remove the matched records"}
    ids = _staged(path, a["db"], match)
    if ids is None:
        ids = _matching(path, match)
    removed, vec = _apply_remove(path, ids)
    if removed:
        try:
            os.remove(os.path.join(str(path), "pending-remove.json"))
        except OSError:
            pass
    return {"db": a["db"], "match": match, "removed": removed, "vectors": vec}


def tool_sources(a):
    path = kb.db_dir(a["db"])
    rows = kb.pack_rows(path)
    seen = {}
    for r in rows:
        key = (_row_url(r), str(r.get("date", "")))
        s = seen.setdefault(key, {"url": key[0], "date": key[1], "records": 0, "sample": r["t"]})
        s["records"] += 1
    srcs = sorted(seen.values(), key=lambda x: (x["date"], x["url"]))
    return {"db": a["db"], "distinct": len(srcs), "sources": srcs}


TOOLS = [
    ("rag_status", "Fork KB status: record count for a db (or all dbs), the db list, and embedding model state. Dbs live under the fork dbs root only.",
     {"type": "object", "properties": {"db": {"type": "string", "description": "database name; omit for all dbs"}}, "required": []}),
    ("rag_search", "Keyword+RRF search over an offline knowledge base, model-off safe. Hits carry id, title, body, source, url and date; empty means not covered: escalate, never guess.",
     {"type": "object", "properties": {"db": {"type": "string"}, "query": {"type": "string"}, "k": {"type": "integer", "default": 5}}, "required": ["db", "query"]}),
    ("rag_ingest_pdf", "Extract text from one local PDF, chunk it and append records with provenance (url=path, src=pdf, date=today). Model-off safe.",
     {"type": "object", "properties": {"db": {"type": "string"}, "path": {"type": "string", "description": "path to one pdf file"}}, "required": ["db", "path"]}),
    ("rag_ingest_urls", "Fetch http(s) pages, strip to text, chunk and append records with provenance (url, src=web, date=today). Model-off safe.",
     {"type": "object", "properties": {"db": {"type": "string"}, "urls": {"type": "array", "items": {"type": "string"}}}, "required": ["db", "urls"]}),
    ("rag_ingest_text", "Ingest text verbatim into a db with owner-grade provenance (title, source, url, date). Use for command references, notes and guides you trust.",
     {"type": "object", "properties": {"db": {"type": "string"}, "title": {"type": "string"}, "text": {"type": "string"},
       "source": {"type": "string", "description": "where this text came from"}, "url": {"type": "string"}, "date": {"type": "string"}}, "required": ["db", "title", "text"]}),
    ("rag_remove", "Remove records whose title/url/source contains match. Refuses without confirm: true (must be the boolean true; empty match refuses outright, nothing ever matches-all), stages pending-remove.json with a preview; re-call with confirm: true to apply.",
     {"type": "object", "properties": {"db": {"type": "string"}, "match": {"type": "string"}, "confirm": {"type": "boolean", "default": False}}, "required": ["db", "match"]}),
    ("rag_list_sources", "Distinct url+date provenance for a db with per-source record counts and a sample title.",
     {"type": "object", "properties": {"db": {"type": "string"}}, "required": ["db"]}),
]

TOOLS_DEF = [{"name": n, "description": d, "inputSchema": s} for n, d, s in TOOLS]


def dispatch(name, a):
    return {
        "rag_status": tool_status, "rag_search": tool_search, "rag_ingest_pdf": tool_ingest_pdf,
        "rag_ingest_urls": tool_ingest_urls, "rag_ingest_text": tool_ingest_text,
        "rag_remove": tool_remove, "rag_list_sources": tool_sources,
    }[name](a or {})


def respond(w, id, res=None, err=None):
    if id is None:
        return
    out = {"jsonrpc": "2.0", "id": id, "result": res} if err is None else {"jsonrpc": "2.0", "id": id, "error": err}
    w.write(json.dumps(out, ensure_ascii=False) + "\n")
    w.flush()


def main():
    w = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        if msg.get("jsonrpc") != "2.0":
            continue
        m, id = msg.get("method", ""), msg.get("id")
        if m == "initialize":
            respond(w, id, {"protocolVersion": PROTO, "capabilities": {"tools": {}}, "serverInfo": SERVER})
        elif m.startswith("notifications/"):
            continue
        elif m == "ping":
            respond(w, id, {})
        elif m == "tools/list":
            respond(w, id, {"tools": TOOLS_DEF})
        elif m == "tools/call":
            n = (msg.get("params") or {}).get("name")
            a = (msg.get("params") or {}).get("arguments", {})
            try:
                r = dispatch(n, a)
                out = dict(r) if isinstance(r, dict) else {"payload": r}
                out["content"] = [{"type": "text", "text": json.dumps(r, ensure_ascii=False)}]
                respond(w, id, out)
            except Exception as e:
                respond(w, id, {"content": [{"type": "text", "text": f"error: {type(e).__name__}: {e}"}], "isError": True})
        elif m in ("shutdown", "exit"):
            return
        elif id is not None:
            respond(w, id, err={"code": -32601, "message": f"method not found: {m}"})


if __name__ == "__main__":
    main()
