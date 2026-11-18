import json, os, subprocess, sys, pathlib
SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "services" / "rag_mcp.py"
SEEDED = "keravex"
TEXT = ("The keravex drill press must sit on a level surface before power is "
        "applied; keravex mirror alignment demands a fixed spindle and a "
        "locked table before any cut is attempted.")
QUERY = "keravex mirror alignment spindle"


def root_guard(tmp_path):
    root = os.environ.get("GREYMICROAGENT_DBS_ROOT")
    assert root == str(tmp_path), "GREYMICROAGENT_DBS_ROOT must be the tmp root before any kbcore import"
    return root


def rpc(proc, obj):
    proc.stdin.write((json.dumps(obj) + "\n").encode()); proc.stdin.flush()
    return json.loads(proc.stdout.readline())


def open_server():
    p = subprocess.Popen([sys.executable, str(SCRIPT)], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    rpc(p, {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}})
    return p


def call(p, i, name, args):
    return rpc(p, {"jsonrpc": "2.0", "id": i, "method": "tools/call",
                   "params": {"name": name, "arguments": args}})


def payload(resp):
    return json.loads(resp["result"]["content"][0]["text"])


def test_research_run_never_stores_without_ingest(tmp_path, monkeypatch):
    monkeypatch.setenv("GREYMICROAGENT_DBS_ROOT", str(tmp_path))
    root_guard(tmp_path)
    p = open_server()
    for i, q in ((1, QUERY), (2, "keravex drill press manual"), (3, "spindle lock")):
        sea = payload(call(p, i, "rag_search", {"db": "commands", "query": q}))
        assert sea["hits"] == 0
    src = payload(call(p, 5, "rag_list_sources", {"db": "commands"}))
    assert src["distinct"] == 0 and src["sources"] == []
    st = payload(call(p, 6, "rag_status", {"db": "commands"}))
    assert st["records"] == 0 and "commands" not in {d["name"] for d in st["dbs"]}
    assert not (tmp_path / "commands" / "pack.jsonl").exists()
    assert not (tmp_path / "commands" / "learned").exists()
    p.kill()


def test_consent_cycle_ingest_firm_hit_remove_unfindable(tmp_path, monkeypatch):
    monkeypatch.setenv("GREYMICROAGENT_DBS_ROOT", str(tmp_path))
    root_guard(tmp_path)
    p = open_server()
    sea0 = payload(call(p, 1, "rag_search", {"db": "commands", "query": QUERY}))
    assert sea0["hits"] == 0
    ing = payload(call(p, 2, "rag_ingest_text", {"db": "commands", "title": "keravex drill press manual",
                   "text": TEXT, "source": "manual", "url": "https://example.test/manual"}))
    assert ing["added"] >= 1
    st = payload(call(p, 3, "rag_status", {"db": "commands"}))
    assert st["records"] > 0 and [d["name"] for d in st["dbs"]] == ["commands"]
    sea = payload(call(p, 4, "rag_search", {"db": "commands", "query": QUERY}))
    assert sea["hits"] >= 1 and SEEDED in sea["text"]
    assert SEEDED in sea["results"][0]["t"] and sea["results"][0]["band"] in ("firm", "soft", "lex-only")
    ref = payload(call(p, 5, "rag_remove", {"db": "commands", "match": "keravex"}))
    assert ref["removed"] == 0 and ref["matched"] >= 1
    assert (tmp_path / "commands" / "pending-remove.json").exists()
    still = payload(call(p, 6, "rag_search", {"db": "commands", "query": QUERY}))
    assert still["hits"] >= 1
    for n, conf in ((7, "true"), (8, False), (9, 1), (10, 0)):
        r = payload(call(p, n, "rag_remove", {"db": "commands", "match": "keravex", "confirm": conf}))
        assert r["removed"] == 0
        kept = payload(call(p, 100 + n, "rag_search", {"db": "commands", "query": QUERY}))
        assert kept["hits"] >= 1
    rem = payload(call(p, 20, "rag_remove", {"db": "commands", "match": "keravex", "confirm": True}))
    assert rem["removed"] >= 1
    assert not (tmp_path / "commands" / "pending-remove.json").exists()
    st2 = payload(call(p, 21, "rag_status", {"db": "commands"}))
    assert st2["records"] == 0
    sea2 = payload(call(p, 22, "rag_search", {"db": "commands", "query": QUERY}))
    assert sea2["hits"] == 0
    p.kill()
