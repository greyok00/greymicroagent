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
DEFAULT_FLOOR = 7.5
DEFAULT_TEMP = 0.1
TEMP_MIN, TEMP_MAX = 0.0, 0.2
THINK_OPEN = "<think>"
THINK_CLOSE = "</think>"


class ThinkStripper:
    def __init__(self):
        self.in_think = False

    def feed(self, text, final=False):
        clean, think, hold = "", "", ""
        t = text
        while t:
            if self.in_think:
                i = t.find(THINK_CLOSE)
                if i >= 0:
                    think += t[:i]
                    t = t[i + len(THINK_CLOSE):]
                    self.in_think = False
                elif final:
                    think += t
                    t = ""
                else:
                    keep = len(THINK_CLOSE) - 1
                    if len(t) > keep:
                        think += t[:-keep]
                        t = t[-keep:]
                    hold = t
                    t = ""
            else:
                i = t.find(THINK_OPEN)
                if i >= 0:
                    clean += t[:i]
                    t = t[i + len(THINK_OPEN):]
                    self.in_think = True
                elif final:
                    clean += t
                    t = ""
                else:
                    keep = len(THINK_OPEN) - 1
                    if len(t) > keep:
                        clean += t[:-keep]
                        t = t[-keep:]
                    hold = t
                    t = ""
        return clean, think, hold


def _strip_message(msg):
    c = msg.get("content")
    if isinstance(c, str) and (THINK_OPEN in c or THINK_CLOSE in c):
        st = ThinkStripper()
        clean, think, _ = st.feed(c, final=True)
        msg["content"] = clean
        if think:
            msg["reasoning_content"] = str(msg.get("reasoning_content") or "") + think
        return True
    return False


def _strip_json_reply(body):
    try:
        data = json.loads(body.decode("utf-8", "ignore"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    changed = False
    for ch in data.get("choices") or []:
        if isinstance(ch, dict):
            if isinstance(ch.get("message"), dict) and _strip_message(ch["message"]):
                changed = True
            d = ch.get("delta")
            if isinstance(d, dict):
                c = d.get("content")
                if isinstance(c, str) and (THINK_OPEN in c or THINK_CLOSE in c):
                    st = ThinkStripper()
                    clean, think, _ = st.feed(c, final=True)
                    d["content"] = clean
                    if think:
                        d["reasoning_content"] = str(d.get("reasoning_content") or "") + think
                    changed = True
            msg = ch.get("messages")
            if isinstance(msg, list):
                for m in msg:
                    if isinstance(m, dict) and _strip_message(m):
                        changed = True
    return json.dumps(data, ensure_ascii=False).encode("utf-8") if changed else None


class SseStripper:
    def __init__(self):
        self.buf = b""
        self.pending = ""
        self.st = ThinkStripper()
        self.ob = THINK_OPEN.encode()
        self.cb = THINK_CLOSE.encode()
        self.engaged = False

    def _delta(self, d, final):
        c = d.get("content")
        if not isinstance(c, str):
            return False
        full = self.pending + c
        clean, think, hold = self.st.feed(full, final=final)
        self.pending = "" if final else hold
        changed = clean != full or bool(think)
        if think:
            d["reasoning_content"] = str(d.get("reasoning_content") or "") + think
        if clean or self.pending:
            if clean:
                d["content"] = clean
            else:
                d.pop("content", None)
        else:
            d.pop("content", None)
        return changed

    def _line(self, raw, final=False):
        # 2026-11-18 (owner red-error cascade): an UNCHANGED chunk used to be
        # returned bare, dropping the "data: " prefix and the newline, so two
        # SSE documents fused on the wire and the client died with
        # "non-whitespace after JSON at position 48". SSE framing is restored
        # on every path: changed or not, one framed line out per line in.
        framed_tail = b"\n"
        try:
            data = json.loads(raw.decode("utf-8", "ignore"))
        except Exception:
            return b"data: " + raw + framed_tail
        if not isinstance(data, dict):
            return b"data: " + raw + framed_tail
        changed = False
        for ch in data.get("choices") or []:
            d = ch.get("delta") if isinstance(ch, dict) else None
            if isinstance(d, dict) and self._delta(d, final):
                changed = True
        if not changed:
            return b"data: " + raw + framed_tail
        return b"data: " + json.dumps(data, ensure_ascii=False).encode("utf-8") + framed_tail

    def feed(self, chunk):
        if not self.engaged:
            self.buf += chunk
            if len(self.buf) < len(self.ob) and self.ob not in self.buf \
                    and self.cb not in self.buf:
                return b""
            self.engaged = True
        else:
            self.buf += chunk
        if len(self.buf) > 1048576:
            rest, self.buf = self.buf, b""
            self.engaged = False
            return rest
        lines = self.buf.split(b"\n")
        self.buf = lines.pop()
        out = []
        for ln in lines:
            s = ln.strip()
            if s.startswith(b"data: [DONE]"):
                out.append(self._tail_event())
                out.append(ln + b"\n")
            elif s.startswith(b"data: "):
                out.append(self._line(s[len(b"data: "):]))
            else:
                out.append(ln + b"\n")
        return b"".join(out)

    def _tail_event(self):
        tail = self.pending
        self.pending = ""
        if not tail:
            return b""
        if self.st.in_think:
            ev = {"choices": [{"delta": {"reasoning_content": tail}}]}
        else:
            ev = {"choices": [{"delta": {"content": tail}}]}
        return b"data: " + json.dumps(ev, ensure_ascii=False).encode("utf-8") + b"\n"

    def flush(self):
        if not self.engaged:
            return b""
        rest = self.buf
        self.buf = b""
        s = rest.strip()
        if s.startswith(b"data: ") and not s.endswith(b"[DONE]"):
            out = self._line(s[len(b"data: "):], final=True)
        else:
            out = rest
            if s.startswith(b"data: [DONE]"):
                out += self._tail_event()
        out += self._tail_event()
        return out


def _upstream():
    return os.environ.get("GREYMICROAGENT_UPSTREAM") or DEFAULT_UPSTREAM


def _floor():
    try:
        return float(os.environ.get("GREYMICROAGENT_RAG_FLOOR"))
    except (TypeError, ValueError):
        return DEFAULT_FLOOR


def _dbs_list():
    out = [x.strip() for x in (os.environ.get("GREYMICROAGENT_DBS") or "commands").split(",") if x.strip()]
    return out or ["commands"]


def _state_dir():
    root = os.environ.get("GREYMICROAGENT_STATE_DIR")
    return Path(root) if root else Path.home() / ".greymicroagent" / "state"


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
    if u.scheme == "https":
        return HTTPSConnection(host, port, timeout=UPSTREAM_TIMEOUT)
    return HTTPConnection(host, port, timeout=UPSTREAM_TIMEOUT)


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



_RUNAWAY_CAP = int(os.environ.get("GREYMICROAGENT_MAX_TOKENS", "8192") or 8192)


def _cap_tokens(req):
    # 2026-11-18 (owner: silent runaway at ~750 tok/s): a repetition loop
    # inside reasoning generated 27k+ invisible tokens because ngram
    # speculative drafting accelerates self-repeats and no max_tokens was
    # set. The gate caps every request so no generation can run forever.
    try:
        n = int(req.get("max_tokens"))
    except (TypeError, ValueError):
        n = None
    req["max_tokens"] = _RUNAWAY_CAP if n is None or n <= 0 else min(n, _RUNAWAY_CAP)


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
    _cap_tokens(req)
    msg = _grounding(req)
    req["messages"].append(msg)
    for ch in req.get("choices") or []:
        if isinstance(ch, dict) and isinstance(ch.get("messages"), list):
            _clamp_carrier(ch)
            _cap_tokens(ch)
            ch["messages"].append(msg)
    return 0, json.dumps(req, ensure_ascii=False).encode("utf-8")


def handle(body, path, upstream):
    code, out = _build(body)
    if code:
        return code, out
    conn = _conn(upstream)
    try:
        conn.request("POST", path, body=out, headers={
            "Content-Type": "application/json",
            "Content-Length": str(len(out)),
            "Accept": "application/json, text/event-stream",
        })
        r = conn.getresponse()
        raw = r.read()
        if r.status == 200:
            stripped = _strip_json_reply(raw)
            if stripped is not None:
                raw = stripped
        return r.status, raw
    except Exception:
        return 0, out
    finally:
        conn.close()


class Gate(BaseHTTPRequestHandler):
    server_version = "greymicroagent-gate"
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
        conn = _conn(_upstream())
        sent = False
        try:
            conn.request(method, self.path, body=body, headers=fwd)
            r = conn.getresponse()
            ctype = (r.headers.get("Content-Type") or "").lower()
            completion_post = method == "POST" and \
                self.path.split("?")[0] == "/v1/chat/completions"
            whole = None
            if completion_post and "text/event-stream" not in ctype:
                whole = r.read()
            self.send_response_only(r.status)
            skip = {"connection", "keep-alive", "transfer-encoding", "content-length"}
            for k, v in r.headers.items():
                if k.lower() not in skip:
                    self.send_header(k, v)
            if whole is not None:
                self.send_header("Content-Length", str(len(whole)))
            else:
                cl = r.headers.get("Content-Length")
                if cl is not None:
                    self.send_header("Content-Length", cl)
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            sent = True
            if whole is not None:
                self.wfile.write(whole)
            elif completion_post and "text/event-stream" in ctype:
                # 2026-11-18 owner order: THIS fork never rewrites its response
                # stream (the only rewriter in the family, and the only one
                # that fused). Frames pass through byte-for-byte; grounding,
                # temperature and max_tokens stay REQUEST-side edits above.
                # llama (booted with --reasoning off) owns reason separation;
                # the SDK decoders own their own robustness.
                while True:
                    b = r.read(8192)
                    if not b:
                        break
                    self.wfile.write(b)
            else:
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
