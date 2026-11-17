import json, subprocess, sys, pathlib
SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "services" / "rag_mcp.py"


def rpc(proc, obj):
    proc.stdin.write((json.dumps(obj) + "\n").encode()); proc.stdin.flush()
    return json.loads(proc.stdout.readline())


def test_ingest_search_remove_cycle(tmp_path, monkeypatch):
    monkeypatch.setenv("GREYLOCALRAG_DBS_ROOT", str(tmp_path))
    p = subprocess.Popen([sys.executable, str(SCRIPT)], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    rpc(p, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    out = rpc(p, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params":
        {"name": "rag_ingest_text", "arguments": {"db": "commands", "title": "ipconfig",
         "text": "ipconfig shows network configuration on Windows 11.", "source": "seed", "url": "u"}}})
    assert "error" not in json.dumps(out["result"])[:200].lower()
    sea = rpc(p, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params":
        {"name": "rag_search", "arguments": {"db": "commands", "query": "network configuration windows"}}})
    assert "ipconfig" in json.dumps(sea)
    rem = rpc(p, {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params":
        {"name": "rag_remove", "arguments": {"db": "commands", "match": "ipconfig", "confirm": True}}})
    assert rem["result"]["removed"] >= 1
    p.kill()


def open_server():
    p = subprocess.Popen([sys.executable, str(SCRIPT)], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    rpc(p, {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}})
    return p


def call(p, i, name, args):
    return rpc(p, {"jsonrpc": "2.0", "id": i, "method": "tools/call",
                   "params": {"name": name, "arguments": args}})


def payload(resp):
    return json.loads(resp["result"]["content"][0]["text"])


def test_remove_refuses_without_confirm(tmp_path, monkeypatch):
    monkeypatch.setenv("GREYLOCALRAG_DBS_ROOT", str(tmp_path))
    p = open_server()
    call(p, 1, "rag_ingest_text", {"db": "commands", "title": "robocopy",
         "text": "robocopy mirrors directories exactly on Windows.", "source": "seed", "url": "u1"})
    ref = payload(call(p, 2, "rag_remove", {"db": "commands", "match": "robocopy"}))
    assert ref.get("removed", 0) == 0 and "confirm" in json.dumps(ref)
    assert (tmp_path / "commands" / "pending-remove.json").exists()
    sea = payload(call(p, 3, "rag_search", {"db": "commands", "query": "mirrors directories"}))
    assert sea["hits"] == 1
    p.kill()


def test_remove_double_call_then_exhausted(tmp_path, monkeypatch):
    monkeypatch.setenv("GREYLOCALRAG_DBS_ROOT", str(tmp_path))
    p = open_server()
    call(p, 1, "rag_ingest_text", {"db": "commands", "title": "netsh",
         "text": "netsh resets the network stack and winsOCK catalog.", "source": "seed", "url": "u2"})
    ref = payload(call(p, 2, "rag_remove", {"db": "commands", "match": "netsh"}))
    assert ref["matched"] == 1
    rem = payload(call(p, 3, "rag_remove", {"db": "commands", "match": "netsh", "confirm": True}))
    assert rem["removed"] == 1
    assert not (tmp_path / "commands" / "pending-remove.json").exists()
    gone = payload(call(p, 4, "rag_remove", {"db": "commands", "match": "netsh", "confirm": True}))
    assert gone["removed"] == 0
    p.kill()


def test_status_and_list_sources(tmp_path, monkeypatch):
    monkeypatch.setenv("GREYLOCALRAG_DBS_ROOT", str(tmp_path))
    p = open_server()
    call(p, 1, "rag_ingest_text", {"db": "commands", "title": "sfc",
         "text": "sfc scans and repairs protected system files.", "source": "seed", "url": "https://x/a"})
    call(p, 2, "rag_ingest_text", {"db": "commands", "title": "dism",
         "text": "dism services and repairs the component store image.", "source": "docs", "url": "https://x/b",
         "date": "2026-11-01"})
    st = payload(call(p, 3, "rag_status", {"db": "commands"}))
    assert st["records"] == 2 and isinstance(st["dbs"], list) and "model_state" in st
    src = payload(call(p, 4, "rag_list_sources", {"db": "commands"}))
    urls = {s["url"] for s in src["sources"]}
    assert urls == {"https://x/a", "https://x/b"}
    p.kill()
