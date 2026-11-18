import json, os, sys, time
import urllib.parse, urllib.request

SERVER = {"name": "greysearch", "version": "0.1.0"}
PROTO = "2024-11-05"
SPACING_S = 3.0
TIMEOUT_S = 25.0
SLICE_S = 0.25
DEFAULT_BASES = "searx.be,search.bus-hit.me,searx.tiekoetter.com"
RUN_FILE_DEFAULT = os.path.expanduser("~/.greymicroagent/state/search-run")
PROBE_QUERY = "greymicroagent search lane probe"
_probe_cache = {}


def _env_f(name, default):
    try:
        return float(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default


def _env_bases():
    raw = os.environ.get("GREYMICROAGENT_SEARX_BASES", "") or DEFAULT_BASES
    out = []
    for part in raw.split(","):
        part = part.strip()
        if part and "://" not in part:
            part = "https://" + part
        if part and part not in out:
            out.append(part)
    return out


def bases():
    return _env_bases()


def run_file():
    return os.environ.get("GREYMICROAGENT_SEARCH_RUN_FILE", "") or RUN_FILE_DEFAULT


def _fetch(url, timeout=TIMEOUT_S):
    req = urllib.request.Request(url, headers={"User-Agent": "greymicroagent-search/0.1"})
    return urllib.request.urlopen(req, timeout=timeout)


def _parse(resp):
    return json.loads(resp.read().decode("utf-8", "ignore"))


def _rows(data):
    if not isinstance(data, dict):
        return None
    rows = data.get("results")
    return rows if isinstance(rows, list) else None


def _hit(r):
    return {"url": str(r.get("url", "")), "title": str(r.get("title", "")),
            "snippet": str(r.get("content", ""))}


def search(query, k=5):
    q = urllib.parse.quote(str(query))
    try:
        k = max(1, int(k))
    except (TypeError, ValueError):
        k = 5
    path = run_file()
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("1")
    except OSError:
        pass
    try:
        listings = bases()
        for i, base in enumerate(listings):
            if i and SPACING_S > 0:
                time.sleep(SPACING_S)
            url = base + "/search?q=" + q + "&format=json"
            data = None
            try:
                resp = _fetch(url, TIMEOUT_S)
                if getattr(resp, "status", 0) == 200:
                    data = _parse(resp)
            except Exception:
                data = None
            rows = _rows(data)
            if rows is not None:
                return [_hit(r) for r in rows if isinstance(r, dict)][:k]
        return []
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def health_wait():
    path = run_file()
    if not os.path.exists(path):
        return 0.0
    t0 = time.time()
    deadline = t0 + max(0.0, _env_f("GREYMICROAGENT_HEALTH_WAIT_S", 240.0))
    while os.path.exists(path):
        now = time.time()
        if now >= deadline:
            break
        time.sleep(min(SLICE_S, deadline - now))
    return time.time() - t0


def _probe_one(base):
    url = base + "/search?q=" + urllib.parse.quote(PROBE_QUERY) + "&format=json"
    try:
        resp = _fetch(url, TIMEOUT_S)
        status = getattr(resp, "status", 0)
        if status != 200:
            return {"base": base, "ok": False, "note": "http " + str(status)}
        rows = _rows(_parse(resp))
        if rows is None:
            return {"base": base, "ok": False, "note": "no json results key"}
        return {"base": base, "ok": True, "results": len(rows)}
    except Exception as e:
        return {"base": base, "ok": False, "note": type(e).__name__}


def _probed_instances(bases_list):
    repoll = max(0.0, _env_f("GREYMICROAGENT_HEALTH_REPOLL_S", 10.0))
    out = []
    for base in bases_list:
        ts, cached = _probe_cache.get(base, (0.0, None))
        if cached is None or time.time() - ts >= repoll:
            cached = _probe_one(base)
            _probe_cache[base] = (time.time(), cached)
        out.append(cached)
    return out


def search_health():
    blocked_s = health_wait()
    bases_list = bases()
    if os.path.exists(run_file()):
        return {"instances": [{"base": b, "ok": None, "note": "unprobed"} for b in bases_list],
                "ok": False, "pending": True,
                "repoll_s": _env_f("GREYMICROAGENT_HEALTH_REPOLL_S", 10.0),
                "blocked_s": round(blocked_s, 3)}
    instances = _probed_instances(bases_list)
    return {"instances": instances, "ok": any(i.get("ok") for i in instances),
            "pending": False, "blocked_s": round(blocked_s, 3)}


def tool_search(a):
    return search((a or {}).get("query", ""), (a or {}).get("k", 5))


def tool_search_health(a):
    return search_health()


TOOLS = [
    ("search", "Keyless public web search over user-configurable SearXNG instances (env GREYMICROAGENT_SEARX_BASES, default searx.be, search.bus-hit.me, searx.tiekoetter.com). Returns a list of {url,title,snippet}; empty means every instance failed or nothing matched: do not fabricate results, escalate or re-state the query.",
     {"type": "object", "properties": {"query": {"type": "string"}, "k": {"type": "integer", "default": 5}}, "required": ["query"]}),
    ("search_health", "Search-lane health: blocks while a marked run file (~/.greymicroagent/state/search-run, env GREYMICROAGENT_SEARCH_RUN_FILE) holds the lane, up to GREYMICROAGENT_HEALTH_WAIT_S (default 240 s), releasing the moment the run clears; after the cap it reports pending: true and re-polls no more than every GREYMICROAGENT_HEALTH_REPOLL_S (default 10 s). Returns {instances, ok} with per-instance probe state.",
     {"type": "object", "properties": {}, "required": []}),
]

TOOLS_DEF = [{"name": n, "description": d, "inputSchema": s} for n, d, s in TOOLS]


def dispatch(name, a):
    return {"search": tool_search, "search_health": tool_search_health}[name](a or {})


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
