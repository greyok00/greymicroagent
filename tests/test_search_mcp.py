import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "services"))
import search_mcp

def test_search_parses_results(monkeypatch):
    class R:
        status = 200
        def read(self): return b'{"results":[{"title":"robocopy doc","url":"https://u","content":"mirrors trees"}]}'
    monkeypatch.setattr(search_mcp, "_fetch", lambda url, t: R())
    out = search_mcp.search("robocopy", 5)
    assert out and out[0]["url"].startswith("https://")

def test_health_blocks_then_clears(tmp_path, monkeypatch):
    runf = tmp_path / "search-run"; runf.write_text("1")
    monkeypatch.setenv("GREYLOCALRAG_SEARCH_RUN_FILE", str(runf))
    monkeypatch.setenv("GREYLOCALRAG_HEALTH_WAIT_S", "12")
    monkeypatch.setenv("GREYLOCALRAG_HEALTH_REPOLL_S", "12")
    import threading, time
    def clear(): time.sleep(13); runf.unlink()
    threading.Thread(target=clear, daemon=True).start()
    t0 = time.time(); search_mcp.health_wait(); assert time.time() - t0 >= 12

def test_wait_releases_the_moment_run_file_clears(tmp_path, monkeypatch):
    import threading, time
    runf = tmp_path / "search-run"; runf.write_text("1")
    monkeypatch.setenv("GREYLOCALRAG_SEARCH_RUN_FILE", str(runf))
    monkeypatch.setenv("GREYLOCALRAG_HEALTH_WAIT_S", "60")
    monkeypatch.setenv("GREYLOCALRAG_HEALTH_REPOLL_S", "10")
    def clear(): time.sleep(1.5); runf.unlink()
    threading.Thread(target=clear, daemon=True).start()
    t0 = time.time()
    waited = search_mcp.health_wait()
    dt = time.time() - t0
    assert 1.0 <= dt < 15.0 and waited >= 1.0 and not runf.exists()

def test_wait_cap_is_bounded_no_wedge(tmp_path, monkeypatch):
    import time
    runf = tmp_path / "search-run"; runf.write_text("1")
    monkeypatch.setenv("GREYLOCALRAG_SEARCH_RUN_FILE", str(runf))
    monkeypatch.setenv("GREYLOCALRAG_HEALTH_WAIT_S", "1")
    monkeypatch.setenv("GREYLOCALRAG_HEALTH_REPOLL_S", "10")
    t0 = time.time()
    waited = search_mcp.health_wait()
    dt = time.time() - t0
    assert runf.exists() and 0.9 <= dt < 5.0 and waited >= 0.9

def test_search_failover_across_instances(monkeypatch):
    import urllib.error
    calls = []
    class R:
        status = 200
        def read(self): return b'{"results":[{"title":"t","url":"https://x/1","content":"s"}]}'
    def fake(url, t):
        calls.append(url)
        if "searx.be" in url:
            raise urllib.error.URLError("blocked")
        return R()
    monkeypatch.setattr(search_mcp, "_fetch", fake)
    monkeypatch.setattr(search_mcp, "SPACING_S", 0.0)
    monkeypatch.setenv("GREYLOCALRAG_SEARX_BASES", "searx.be, search.bus-hit.me")
    out = search_mcp.search("q", 2)
    assert out == [{"url": "https://x/1", "title": "t", "snippet": "s"}]
    assert len(calls) == 2 and "searx.be" in calls[0] and "search.bus-hit.me" in calls[1]

def test_search_k_caps_and_missing_fields_tolerated(monkeypatch):
    class R:
        status = 200
        def read(self): return b'{"results":[{"title":"a","url":"https://a","content":"x"},{"title":"b","url":"https://b"},{"url":"https://c"},{"title":"d","url":"https://d"}]}'
    monkeypatch.setattr(search_mcp, "_fetch", lambda url, t: R())
    monkeypatch.setenv("GREYLOCALRAG_SEARX_BASES", "searx.be")
    out = search_mcp.search("q", 3)
    assert len(out) == 3 and out[0]["snippet"] == "x" and out[1]["snippet"] == "" and out[2]["title"] == ""

def test_search_all_instances_fail_returns_empty(monkeypatch):
    import urllib.error
    def fake(url, t):
        raise urllib.error.URLError("down")
    monkeypatch.setattr(search_mcp, "_fetch", fake)
    monkeypatch.setattr(search_mcp, "SPACING_S", 0.0)
    monkeypatch.setenv("GREYLOCALRAG_SEARX_BASES", "a.test,b.test")
    assert search_mcp.search("q", 5) == []

def test_spacing_constant_is_three_seconds():
    assert search_mcp.SPACING_S == 3.0 and search_mcp.TIMEOUT_S == 25.0

def test_health_pending_after_cap_skips_probe(tmp_path, monkeypatch):
    import time
    runf = tmp_path / "search-run"; runf.write_text("1")
    monkeypatch.setenv("GREYLOCALRAG_SEARCH_RUN_FILE", str(runf))
    monkeypatch.setenv("GREYLOCALRAG_HEALTH_WAIT_S", "1")
    monkeypatch.setenv("GREYLOCALRAG_HEALTH_REPOLL_S", "10")
    monkeypatch.setenv("GREYLOCALRAG_SEARX_BASES", "a.test")
    hits = []
    class R:
        status = 200
        def read(self): return b'{"results":[{"title":"t","url":"https://u","content":"c"}]}'
    def fake(url, t):
        hits.append(url); return R()
    monkeypatch.setattr(search_mcp, "_fetch", fake)
    h = search_mcp.search_health()
    assert h["pending"] is True and h["ok"] is False and hits == []
    assert runf.exists()
    runf.unlink()
    h2 = search_mcp.search_health()
    assert len(hits) == 1 and h2["ok"] is True and h2["pending"] is False
    h3 = search_mcp.search_health()
    assert len(hits) == 1 and h3["ok"] is True

def test_stdio_server_pending_health_offline(tmp_path):
    import json, subprocess, os
    runf = tmp_path / "search-run"; runf.write_text("1")
    script = pathlib.Path(__file__).resolve().parents[1] / "services" / "search_mcp.py"
    env = {**os.environ, "GREYLOCALRAG_SEARCH_RUN_FILE": str(runf),
           "GREYLOCALRAG_HEALTH_WAIT_S": "0", "GREYLOCALRAG_SEARX_BASES": "a.test"}
    p = subprocess.Popen([sys.executable, str(script)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env)
    def rpc(i, m, params=None):
        msg = {"jsonrpc": "2.0", "id": i, "method": m}
        if params is not None:
            msg["params"] = params
        p.stdin.write((json.dumps(msg) + "\n").encode()); p.stdin.flush()
        return json.loads(p.stdout.readline())
    init = rpc(1, "initialize", {})
    assert init["result"]["serverInfo"]["name"] == "greysearch"
    tools = rpc(2, "tools/list", {})["result"]["tools"]
    assert {t["name"] for t in tools} == {"search", "search_health"}
    h = rpc(3, "tools/call", {"name": "search_health", "arguments": {}})["result"]
    assert h["pending"] is True and h["ok"] is False and "content" in h
    p.stdin.write((json.dumps({"jsonrpc": "2.0", "id": 4, "method": "shutdown"}) + "\n").encode()); p.stdin.flush()
    p.wait(timeout=5)

def test_search_health_absent_run_file_probes_instently(tmp_path, monkeypatch):
    monkeypatch.delenv("GREYLOCALRAG_SEARCH_RUN_FILE", raising=False)
    monkeypatch.setenv("GREYLOCALRAG_HEALTH_REPOLL_S", "300")
    monkeypatch.setattr(search_mcp, "_probe_cache", {})
    class R:
        status = 200
        def read(self): return b'{"results":[]}'
    monkeypatch.setattr(search_mcp, "_fetch", lambda url, t: R())
    monkeypatch.setenv("GREYLOCALRAG_SEARX_BASES", "a.test,b.test")
    h = search_mcp.search_health()
    assert h["ok"] is True and [i["base"] for i in h["instances"]] == ["https://a.test", "https://b.test"]

def test_search_marks_run_in_flight_and_clears_after(tmp_path, monkeypatch):
    import time
    runf = tmp_path / "search-run"
    monkeypatch.setenv("GREYLOCALRAG_SEARCH_RUN_FILE", str(runf))
    monkeypatch.setattr(search_mcp, "SPACING_S", 0.0)
    monkeypatch.setattr(search_mcp, "bases", lambda: ["a.test"])
    seen = {}
    class R:
        status = 200
        def read(self):
            seen["during"] = runf.exists()
            time.sleep(0.2)
            return b'{"results":[{"title":"t","url":"https://u","content":"c"}]}'
    monkeypatch.setattr(search_mcp, "_fetch", lambda url, t: R())
    out = search_mcp.search("q", 5)
    assert out == [{"url": "https://u", "title": "t", "snippet": "c"}]
    assert seen["during"] is True and not runf.exists()

def test_search_all_fail_clears_run_marker(tmp_path, monkeypatch):
    import urllib.error
    runf = tmp_path / "search-run"
    monkeypatch.setenv("GREYLOCALRAG_SEARCH_RUN_FILE", str(runf))
    monkeypatch.setattr(search_mcp, "SPACING_S", 0.0)
    monkeypatch.setattr(search_mcp, "bases", lambda: ["bad.test", "garbage.test"])
    calls = []
    class Bad:
        status = 200
        def read(self): return b"not json at all"
    def fake(url, t):
        calls.append(url)
        if "garbage.test" in url:
            return Bad()
        raise urllib.error.URLError("down")
    monkeypatch.setattr(search_mcp, "_fetch", fake)
    out = search_mcp.search("q", 5)
    assert out == [] and len(calls) == 2 and not runf.exists()
