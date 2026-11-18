import json, os, pathlib, subprocess, sys, threading, time
import http.server
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "services" / "browser_mcp.py"
sys.path.insert(0, str(ROOT / "services"))
import browser_mcp

TITLE = "greylocalrag browser fixture"
MARKER = "the quick brown fox marker ZXQ77"
LINK_HREF = "https://example.org/fixture-target"
LINK_TEXT = "fixture link text"
PAGE_BODY = (
    "<html><head><title>%s</title></head><body>"
    "<h1>fixture heading</h1><p>%s</p>"
    "<a href=\"%s\">%s</a>"
    "</body></html>" % (TITLE, MARKER, LINK_HREF, LINK_TEXT)
).encode("utf-8")


def _serve_fixture():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(PAGE_BODY)))
            self.end_headers()
            self.wfile.write(PAGE_BODY)

        def log_message(self, fmt, *args):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _rpc(proc):
    def call(i, method, params=None):
        box = {}

        def work():
            msg = {"jsonrpc": "2.0", "id": i, "method": method}
            if params is not None:
                msg["params"] = params
            proc.stdin.write(json.dumps(msg) + "\n")
            proc.stdin.flush()
            box["resp"] = json.loads(proc.stdout.readline())

        th = threading.Thread(target=work, daemon=True)
        th.start()
        th.join(90.0)
        if "resp" not in box:
            proc.kill()
            pytest.fail("browser mcp call %s id %s got no answer in 90 s" % (method, i))
        return box["resp"]

    return call


def _popen(tmp_path):
    env = {**os.environ, "GREYLOCALRAG_BROWSER_PIDS": str(tmp_path / "pids.json")}
    return subprocess.Popen([sys.executable, str(SCRIPT)], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, env=env, text=True, bufsize=1)


def _kill(proc):
    if proc.poll() is None:
        proc.kill()
        proc.wait(10)


def _res(r):
    return {k: v for k, v in r.items() if k != "content"}


def _read_pids(path):
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    return data["server_pid"], {int(pid): base for pid, base in data["pids"].items()}


def _chrome_pids(pid_map):
    return [p for p, sig in pid_map.items()
            if any(marker in sig for marker in browser_mcp.CHROME_MARKERS)]


def _pid_alive(pid):
    try:
        with open("/proc/%d/stat" % pid, "r", encoding="utf-8", errors="ignore") as f:
            raw = f.read()
    except OSError:
        return False
    cut = raw.rfind(")")
    if cut < 0:
        return False
    parts = raw[cut + 1:].split()
    return bool(parts) and parts[0] != "Z"


def _wait_dead(pids, deadline_s=20.0):
    deadline = time.time() + deadline_s
    while time.time() < deadline and any(_pid_alive(p) for p in pids):
        time.sleep(0.1)
    return [p for p in pids if _pid_alive(p)]


def test_cold_never_launches(tmp_path):
    pids_path = tmp_path / "pids.json"
    proc = _popen(tmp_path)
    try:
        call = _rpc(proc)
        init = call(1, "initialize", {})
        assert init["result"]["serverInfo"]["name"] == "browser"
        tools = call(2, "tools/list", {})["result"]["tools"]
        assert {t["name"] for t in tools} == {"browser_open", "browser_close", "browser_health"}
        h = call(3, "tools/call", {"name": "browser_health", "arguments": {}})["result"]
        assert _res(h) == {"browser": "cold", "pages_open": 0}
        c = call(4, "tools/call", {"name": "browser_close", "arguments": {}})["result"]
        assert _res(c)["closed"] is True and _res(c)["cold"] is True
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 5, "method": "shutdown"}) + "\n")
        proc.stdin.flush()
        assert proc.wait(15) == 0, "clean shutdown must exit 0"
    finally:
        _kill(proc)
    assert not pids_path.exists(), "a cold server must never launch or record a browser"


def test_cold_unit_pins():
    h = browser_mcp.tool_browser_health({})
    assert h == {"browser": "cold", "pages_open": 0}
    assert browser_mcp._state["browser"] is None and browser_mcp._state["pw"] is None
    r = browser_mcp.tool_browser_open({})
    assert "error" in r and "text" not in r and "title" not in r
    r2 = browser_mcp.tool_browser_open({"url": "file:///etc/hostname"})
    assert "error" in r2 and "text" not in r2 and "title" not in r2


def test_live_open_extract_reuse_close_no_survivors(tmp_path):
    srv = _serve_fixture()
    port = srv.server_address[1]
    url = "http://127.0.0.1:%d/" % port
    pids_path = tmp_path / "pids.json"
    proc = _popen(tmp_path)
    try:
        call = _rpc(proc)
        call(1, "initialize", {})
        h0 = call(2, "tools/call", {"name": "browser_health", "arguments": {}})["result"]
        assert _res(h0) == {"browser": "cold", "pages_open": 0}
        r1 = call(3, "tools/call", {"name": "browser_open", "arguments": {"url": url}})["result"]
        assert "error" not in r1, r1
        assert r1["title"] == TITLE, r1
        assert MARKER in r1["text"], r1
        assert r1["url_final"] == url
        assert isinstance(r1["elapsed_s"], (int, float)) and r1["elapsed_s"] >= 0.0
        assert any(l["href"] == LINK_HREF and l["text"] == LINK_TEXT for l in r1["links"]), r1["links"]
        server_pid, pids_after_open = _read_pids(pids_path)
        assert server_pid == proc.pid
        chrome_pids = _chrome_pids(pids_after_open)
        assert chrome_pids, "the open must have spawned a real chromium: %r" % pids_after_open
        payload_before = pids_path.read_bytes()
        r2 = call(4, "tools/call", {"name": "browser_open",
                                    "arguments": {"url": url + "?again=1"}})["result"]
        assert "error" not in r2, r2
        assert MARKER in r2["text"]
        assert pids_path.read_bytes() == payload_before, \
            "the second open must reuse the one shared browser, not spawn another"
        h1 = call(5, "tools/call", {"name": "browser_health", "arguments": {}})["result"]
        assert _res(h1) == {"browser": "ready", "pages_open": 0}
        r3 = call(6, "tools/call", {"name": "browser_open",
                                    "arguments": {"url": "http://127.0.0.1:1/"}})["result"]
        assert "error" in r3 and "text" not in r3 and "title" not in r3, r3
        c = call(7, "tools/call", {"name": "browser_close", "arguments": {}})["result"]
        assert c["closed"] is True
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 8, "method": "shutdown"}) + "\n")
        proc.stdin.flush()
        assert proc.wait(40) == 0, "shutdown after a live run must exit 0"
    finally:
        _kill(proc)
        srv.shutdown()
        srv.server_close()
    _, final_pids = _read_pids(pids_path)
    assert final_pids, "the final record must still carry what the launch spawned"
    survivors = _wait_dead(_chrome_pids(final_pids))
    assert survivors == [], "recorded chromium pids must be gone after close+exit: %r" % survivors
