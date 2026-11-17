import sys, json, pathlib, tempfile, io
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "services"))
import rag_gate

BODY = {"model": "greylocalrag", "temperature": 0.9,
        "messages": [{"role": "user", "content": "how do I mirror directories"}]}

NOTEMP = {"model": "greylocalrag",
          "messages": [{"role": "user", "content": "how do I mirror directories"}]}

def test_temp_clamped():
    code, out = rag_gate.handle(json.dumps(BODY).encode(), "/v1/chat/completions", "http://127.0.0.1:1")
    req = json.loads(out)
    assert 0.0 <= req["temperature"] <= 0.2

def test_no_grounding_marker_on_empty_kb(tmp_path, monkeypatch):
    monkeypatch.setenv("GREYLOCALRAG_DBS_ROOT", str(tmp_path))
    monkeypatch.delenv("GREYLOCALRAG_DBS", raising=False)
    code, out = rag_gate.handle(json.dumps(BODY).encode(), "/v1/chat/completions", "http://127.0.0.1:1")
    msgs = json.loads(out)["messages"]
    assert json.dumps(msgs[-1]).find("NO-KB-GROUNDING") >= 0

def test_grounding_block_injected(tmp_path, monkeypatch):
    import rag.kbcore as kb
    dbs = tmp_path / "dbs"; dbs.mkdir()
    monkeypatch.setenv("GREYLOCALRAG_DBS_ROOT", str(dbs))
    monkeypatch.setenv("GREYLOCALRAG_DBS", "commands")
    monkeypatch.setenv("GREYLOCALRAG_RAG_FLOOR", "0.0")
    db = kb.db_dir("commands"); kb.init_db(db, note="t")
    kb.add_records(db, kb.records_from("robocopy /MIR mirrors a directory tree exactly and completely.", {"t": "robocopy", "src": "t", "url": "u", "date": "d"}), enc=None)
    code, out = rag_gate.handle(json.dumps(BODY).encode(), "/v1/chat/completions", "http://127.0.0.1:1")
    last = json.loads(out)["messages"][-1]["content"]
    assert "[KB:commands#1 score=" in last and "robocopy" in last

def test_no_request_logging(tmp_path):
    assert not list(tmp_path.rglob("*.log"))

def test_temp_state_file_applied(tmp_path, monkeypatch):
    monkeypatch.setenv("GREYLOCALRAG_STATE_DIR", str(tmp_path))
    body = json.dumps(NOTEMP).encode()
    for text, want in (("0.05", 0.05), ("0.9", 0.2), ("garbage", 0.1), ("0.0", 0.0)):
        (tmp_path / "rag-temp").write_text(text)
        got = json.loads(rag_gate.handle(body, "/v1/chat/completions", "http://127.0.0.1:1")[1])["temperature"]
        assert abs(got - want) < 1e-9, text
    (tmp_path / "rag-temp").unlink()
    got = json.loads(rag_gate.handle(body, "/v1/chat/completions", "http://127.0.0.1:1")[1])["temperature"]
    assert abs(got - 0.1) < 1e-9

def test_request_null_or_garbage_temp_uses_default(tmp_path, monkeypatch):
    monkeypatch.setenv("GREYLOCALRAG_STATE_DIR", str(tmp_path))
    (tmp_path / "rag-temp").write_text("0.05")
    for bad in (None, "hot"):
        req = dict(NOTEMP)
        req["temperature"] = bad
        body = json.dumps(req).encode()
        got = json.loads(rag_gate.handle(body, "/v1/chat/completions", "http://127.0.0.1:1")[1])["temperature"]
        assert abs(got - 0.1) < 1e-9, bad

def test_carrier_temperatures_clamped(tmp_path, monkeypatch):
    monkeypatch.setenv("GREYLOCALRAG_STATE_DIR", str(tmp_path))
    (tmp_path / "rag-temp").write_text("0.15")
    req = dict(NOTEMP)
    req["temperature"] = "hot"
    req["choices"] = [
        {"temperature": 0.9, "messages": [{"role": "user", "content": "a"}]},
        {"temperature": None, "messages": [{"role": "user", "content": "b"}]},
        {"messages": [{"role": "user", "content": "c"}]},
        {"temperature": 0.05, "messages": [{"role": "user", "content": "d"}]},
    ]
    out = json.loads(rag_gate.handle(json.dumps(req).encode(), "/v1/chat/completions", "http://127.0.0.1:1")[1])
    assert abs(out["temperature"] - 0.1) < 1e-9
    c1, c2, c3, c4 = out["choices"]
    assert abs(c1["temperature"] - 0.2) < 1e-9
    assert abs(c2["temperature"] - 0.1) < 1e-9
    assert abs(c4["temperature"] - 0.05) < 1e-9
    assert "temperature" not in c3
    assert c3["messages"][-1]["role"] == "system"

def test_offline_toggle_marks_offline(tmp_path, monkeypatch):
    monkeypatch.setenv("GREYLOCALRAG_STATE_DIR", str(tmp_path))
    body = json.dumps(NOTEMP).encode()
    content = lambda: json.loads(rag_gate.handle(body, "/v1/chat/completions", "http://127.0.0.1:1")[1])["messages"][-1]["content"]
    assert "OFFLINE-MODE" not in content()
    (tmp_path / "rag-offline").write_text("")
    assert "OFFLINE-MODE" in content()
    (tmp_path / "rag-offline").unlink()
    assert "OFFLINE-MODE" not in content()

def test_get_metrics_passthrough(monkeypatch):
    seen = {}
    class FakeResp:
        def __init__(self):
            self.status = 200
            self.headers = {"Content-Type": "application/json", "Content-Length": "9"}
            self._chunks = [b'{"m":123}', b""]
        def read(self, _n):
            return self._chunks.pop(0)
    class FakeConn:
        def __init__(self, host, port, timeout=None):
            pass
        def request(self, method, path, body=None, headers=None):
            seen["req"] = (method, path, body, dict(headers))
        def getresponse(self):
            return FakeResp()
        def close(self):
            pass
    monkeypatch.setattr(rag_gate, "HTTPConnection", FakeConn)
    out = io.BytesIO()
    h = object.__new__(rag_gate.Gate)
    h.path = "/metrics"
    h.request_version = "HTTP/1.1"
    h.headers = {}
    h.wfile = out
    h.do_GET()
    method, path, body, headers = seen["req"]
    assert (method, path, body) == ("GET", "/metrics", None)
    payload = out.getvalue()
    assert b'{"m":123}' in payload
    assert b"Content-Length: 9" in payload and b"Connection: close" in payload and b"Transfer-Encoding" not in payload

def test_post_forwards_received_path(tmp_path, monkeypatch):
    monkeypatch.setenv("GREYLOCALRAG_DBS_ROOT", str(tmp_path))
    monkeypatch.setenv("GREYLOCALRAG_STATE_DIR", str(tmp_path))
    seen = {}
    class FakeResp:
        def __init__(self):
            self.status = 200
            self.headers = {"Content-Type": "application/json", "Content-Length": "2"}
            self._chunks = [b"ok", b""]
        def read(self, _n):
            return self._chunks.pop(0)
    class FakeConn:
        def __init__(self, host, port, timeout=None):
            pass
        def request(self, method, path, body=None, headers=None):
            seen["req"] = (method, path, body)
        def getresponse(self):
            return FakeResp()
        def close(self):
            pass
    monkeypatch.setattr(rag_gate, "HTTPConnection", FakeConn)
    out = io.BytesIO()
    h = object.__new__(rag_gate.Gate)
    h.path = "/v1/chat/completions"
    h.requestline = "POST /v1/chat/completions HTTP/1.1"
    h.request_version = "HTTP/1.1"
    h.headers = {"Content-Type": "application/json", "Content-Length": str(len(json.dumps(BODY).encode()))}
    h.wfile = out
    h.rfile = io.BytesIO(json.dumps(BODY).encode())
    h.do_POST()
    method, path, body = seen["req"]
    assert (method, path) == ("POST", "/v1/chat/completions")
    up = json.loads(body)
    assert up["temperature"] <= 0.2 and "NO-KB-GROUNDING" in up["messages"][-1]["content"]
    payload = out.getvalue()
    assert b"HTTP/1.1 200 OK" in payload and b"ok" in payload

def test_post_unrouted_paths_forward_verbatim(tmp_path, monkeypatch):
    monkeypatch.setenv("GREYLOCALRAG_DBS_ROOT", str(tmp_path))
    monkeypatch.setenv("GREYLOCALRAG_STATE_DIR", str(tmp_path))
    seen = {}
    class FakeResp:
        def __init__(self):
            self.status = 200
            self.headers = {"Content-Type": "application/json", "Content-Length": "2"}
            self._chunks = [b"ok", b""]
        def read(self, _n):
            return self._chunks.pop(0)
    class FakeConn:
        def __init__(self, host, port, timeout=None):
            pass
        def request(self, method, path, body=None, headers=None):
            seen["req"] = (method, path)
        def getresponse(self):
            return FakeResp()
        def close(self):
            pass
    monkeypatch.setattr(rag_gate, "HTTPConnection", FakeConn)
    out = io.BytesIO()
    h = object.__new__(rag_gate.Gate)
    h.path = "/health"
    h.requestline = "POST /health HTTP/1.1"
    h.request_version = "HTTP/1.1"
    h.headers = {"Content-Type": "application/json", "Content-Length": str(len(json.dumps(BODY).encode()))}
    h.wfile = out
    h.rfile = io.BytesIO(json.dumps(BODY).encode())
    h.do_POST()
    assert seen["req"] == ("POST", "/health")
    payload = out.getvalue()
    assert b"HTTP/1.1 200 OK" in payload and b"ok" in payload

def test_handle_forwards_received_path_not_upstream_path(monkeypatch):
    seen = {}
    class FakeResp:
        status = 200
        headers = {"Content-Length": "2"}
        def read(self, *a):
            return b"ok"
    class FakeConn:
        def __init__(self, host, port, timeout=None):
            pass
        def request(self, method, path, body=None, headers=None):
            seen["req"] = (method, path)
        def getresponse(self):
            return FakeResp()
        def close(self):
            pass
    monkeypatch.setattr(rag_gate, "HTTPConnection", FakeConn)
    code, out = rag_gate.handle(json.dumps(BODY).encode(), "/v1/chat/completions", "http://127.0.0.1:9/chat")
    assert code == 200
    assert seen["req"] == ("POST", "/v1/chat/completions")
