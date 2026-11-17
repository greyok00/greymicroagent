import json, os
from http.client import HTTPConnection, HTTPSConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
import rag.kbcore as kb

DEFAULT_UPSTREAM = "http://127.0.0.1:7642"
DEFAULT_PORT = 7641
UPSTREAM_TIMEOUT = 1800
QUERY_LEN, CHUNK_LEN, CHUNK_CAP, TEXT_CAP = 400, 800, 6, 4800
DEFAULT_FLOOR = 0.25
DEFAULT_TEMP = 0.1
TEMP_MIN, TEMP_MAX = 0.0, 0.2


def _upstream():
    return os.environ.get("GREYLOCALRAG_UPSTREAM") or DEFAULT_UPSTREAM


def _floor():
    try:
        return float(os.environ.get("GREYLOCALRAG_RAG_FLOOR"))
    except (TypeError, ValueError):
        return DEFAULT_FLOOR


def _dbs_list():
    out = [x.strip() for x in (os.environ.get("GREYLOCALRAG_DBS") or "commands").split(",") if x.strip()]
    return out or ["commands"]


def _state_dir():
    root = os.environ.get("GREYLOCALRAG_STATE_DIR")
    return Path(root) if root else Path.home() / ".greylocalrag" / "state"


def _offline():
    return (_state_dir() / "rag-offline").exists()


def _state_temp():
    try:
        f = float((_state_dir() / "rag-temp").read_text(encoding="utf-8", errors="ignore").strip())
    except (OSError, ValueError):
        return None
    return f if f == f else None


def _conn(upstream):
    u = urlsplit(upstream if isinstance(upstream, str) else "")
    host = u.hostname or "127.0.0.1"
    port = u.port or (443 if u.scheme == "https" else 80)
    path = (u.path or "/") + (f"?{u.query}" if u.query else "")
    if u.scheme == "https":
        return path, HTTPSConnection(host, port, timeout=UPSTREAM_TIMEOUT)
    return path, HTTPConnection(host, port, timeout=UPSTREAM_TIMEOUT)


def _query(req):
    pools = [req.get("messages") or []]
    pools += [(ch.get("messages") or []) for ch in (req.get("choices") or []) if isinstance(ch, dict)]
    for pool in pools:
        for msg in reversed(pool):
            if isinstance(msg, dict) and msg.get("role") == "user":
                c = msg.get("content", "")
                if isinstance(c, list):
                    c = " ".join(x.get("text", "") for x in c if isinstance(x, dict))
                return str(c).strip()[:QUERY_LEN].strip()
    return ""


def _chunks(q):
    floor = _floor()
    out, total = [], 0
    for name in _dbs_list():
        try:
            path = kb.db_dir(name)
        except ValueError:
            continue
        for j, h in enumerate(kb.search(path, q, CHUNK_CAP, enc=None), 1):
            if len(out) >= CHUNK_CAP or total >= TEXT_CAP:
                return out, total
            s = max(float(h.get("cos") or 0.0), float(h.get("lex") or 0.0))
            if s < floor:
                continue
            text = str(h.get("x") or "")[:CHUNK_LEN].strip()
            if not text:
                continue
            block = f"[KB:{name}#{j} score={s:.2f}] {text}"
            if total + len(block) > TEXT_CAP:
                break
            total += len(block) + 1
            out.append(block)
    return out, total


def _grounding(req):
    blocks, _t = _chunks(_query(req))
    body = "GROUNDING:\n" + "\n".join(blocks) if blocks else "[NO-KB-GROUNDING]"
    if _offline():
        body += "\n[OFFLINE-MODE] answering from your KB only"
    return {"role": "system", "content": body}


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _band(v):
    return min(max(v, TEMP_MIN), TEMP_MAX)


def _clamp(req):
    if "temperature" in req:
        t = _num(req.get("temperature"))
        req["temperature"] = _band(t) if t is not None else DEFAULT_TEMP
        return
    s = _state_temp()
    req["temperature"] = _band(s if s is not None else DEFAULT_TEMP)


def _clamp_carrier(ch):
    if "temperature" not in ch:
        return
    t = _num(ch.get("temperature"))
    ch["temperature"] = _band(t) if t is not None else DEFAULT_TEMP


def _build(body):
    try:
        req = json.loads(bytes(body or b"").decode("utf-8", "ignore"))
    except Exception:
        return 400, b'{"error":"bad json"}'
    if not isinstance(req, dict) or not isinstance(req.get("messages"), list):
        return 400, b'{"error":"no messages array"}'
    _clamp(req)
    msg = _grounding(req)
    req["messages"].append(msg)
    for ch in req.get("choices") or []:
        if isinstance(ch, dict) and isinstance(ch.get("messages"), list):
            _clamp_carrier(ch)
            ch["messages"].append(msg)
    return 0, json.dumps(req, ensure_ascii=False).encode("utf-8")


def handle(body, upstream):
    code, out = _build(body)
    if code:
        return code, out
    path, conn = _conn(upstream)
    try:
        conn.request("POST", path, body=out, headers={
            "Content-Type": "application/json",
            "Content-Length": str(len(out)),
            "Accept": "application/json, text/event-stream",
        })
        r = conn.getresponse()
        return r.status, r.read()
    except Exception:
        return 0, out
    finally:
        conn.close()


class Gate(BaseHTTPRequestHandler):
    server_version = "greylocalrag-gate"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.split("?")[0] == "/health":
            self._plain(200, b'{"status":"ok"}')
        else:
            self._proxy("GET")

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        body = self.rfile.read(n) if n > 0 else b""
        code, out = _build(body)
        if code:
            self._plain(code, out)
            return
        self._stream(out)

    def _plain(self, code, payload):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        self.wfile.write(payload)

    def _stream(self, body):
        self._proxy("POST", body)

    def _proxy(self, method, body=None):
        fwd = {"Accept": "application/json, text/event-stream" if body is not None else "*/*"}
        auth = self.headers.get("Authorization")
        if auth:
            fwd["Authorization"] = auth
        if body is not None:
            fwd["Content-Type"] = "application/json"
            fwd["Content-Length"] = str(len(body))
        up_path, conn = _conn(_upstream())
        sent = False
        try:
            conn.request(method, self.path if method == "GET" else up_path, body=body, headers=fwd)
            r = conn.getresponse()
            self.send_response_only(r.status)
            skip = {"connection", "keep-alive", "transfer-encoding", "content-length"}
            for k, v in r.headers.items():
                if k.lower() not in skip:
                    self.send_header(k, v)
            cl = r.headers.get("Content-Length")
            if cl is not None:
                self.send_header("Content-Length", cl)
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            sent = True
            while True:
                b = r.read(8192)
                if not b:
                    break
                self.wfile.write(b)
            self.wfile.flush()
        except Exception:
            if not sent:
                try:
                    self._plain(502, b'{"error":"upstream unreachable"}')
                except Exception:
                    pass
        finally:
            conn.close()


def run():
    port = int(os.environ.get("RAG_GATE_PORT") or DEFAULT_PORT)
    ThreadingHTTPServer(("127.0.0.1", port), Gate).serve_forever()


if __name__ == "__main__":
    run()
