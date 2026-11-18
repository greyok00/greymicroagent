import asyncio, atexit, json, os, signal, sys, threading, time

SERVER = {"name": "browser", "version": "0.1.0"}
PROTO = "2024-11-05"
NAV_TIMEOUT_S = 25.0
LAUNCH_TIMEOUT_S = 8.0
CLOSE_TIMEOUT_S = 12.0
CALL_TIMEOUT_S = 35.0
TEXT_LIMIT_CHARS = 8000
TITLE_LIMIT_CHARS = 200
LINK_LIMIT = 20
LINK_TEXT_LIMIT = 200
EXE_ENV = "GREYMICROAGENT_BROWSER_EXE"
PIDS_ENV = "GREYMICROAGENT_BROWSER_PIDS"
SIGNATURE_LIMIT = 300
CHROME_MARKERS = ("/chrome", "/chromium", "/headless_shell", "ms-playwright",
                  "playwright_chromiumdev_profile", "--remote-debugging-pipe")
READABLE_TYPES = frozenset((
    "text/html", "text/plain", "application/xhtml+xml", "text/xml",
    "application/xml", "application/json", "text/markdown", "text/csv"))

_state = {"pw": None, "browser": None, "pages": 0, "pids": {}, "written": None}
_loop = None
_ready = threading.Event()
_loop_lock = threading.Lock()


def _pump(loop):
    asyncio.set_event_loop(loop)
    _ready.set()
    loop.run_forever()


def _get_loop():
    global _loop
    if _loop is None:
        with _loop_lock:
            if _loop is None:
                new = asyncio.new_event_loop()
                threading.Thread(target=_pump, args=(new,), daemon=True,
                                 name="browser-loop").start()
                _loop = new
    if not _ready.wait(2.0):
        raise RuntimeError("browser event loop thread did not start")
    return _loop


def _call(coro, timeout=CALL_TIMEOUT_S):
    fut = asyncio.run_coroutine_threadsafe(coro, _get_loop())
    return fut.result(timeout)


def _proc_stat(pid):
    try:
        with open("/proc/%d/stat" % pid, "r", encoding="utf-8", errors="ignore") as f:
            raw = f.read()
    except OSError:
        return ""
    cut = raw.rfind(")")
    if cut < 0:
        return ""
    parts = raw[cut + 1:].split()
    return parts[0] if parts else ""


def _signature(pid):
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as f:
            raw = f.read()
    except OSError:
        return ""
    text = raw.replace(b"\x00", b" ").decode("utf-8", "ignore").strip()
    return text[:SIGNATURE_LIMIT]


def _chrome_like(sig):
    return any(marker in sig for marker in CHROME_MARKERS)


def _descendants(root):
    rows = {}
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        st = _proc_stat(int(name))
        if not st:
            continue
        try:
            with open("/proc/%s/stat" % name, "r", encoding="utf-8", errors="ignore") as f:
                raw = f.read()
        except OSError:
            continue
        cut = raw.rfind(")")
        if cut < 0:
            continue
        parts = raw[cut + 1:].split()
        if len(parts) < 2:
            continue
        try:
            rows[int(name)] = int(parts[1])
        except ValueError:
            continue
    kids = {}
    for pid, ppid in rows.items():
        kids.setdefault(ppid, []).append(pid)
    out, queue = set(), [root]
    while queue:
        cur = queue.pop()
        for child in kids.get(cur, ()):
            if child not in out:
                out.add(child)
                queue.append(child)
    return out


def _record():
    pids = dict(_state["pids"])
    for pid in sorted(_descendants(os.getpid())):
        if _proc_stat(pid) == "Z":
            continue
        sig = _signature(pid)
        if sig:
            pids[pid] = sig
    _state["pids"] = pids
    payload = json.dumps({"server_pid": os.getpid(),
                          "pids": {str(pid): base for pid, base in sorted(pids.items())}})
    path = (os.environ.get(PIDS_ENV, "") or "").strip()
    if pids and path and payload != _state["written"]:
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(payload)
            _state["written"] = payload
        except OSError:
            pass
    return pids


def _alive_pids(pid_map, chrome_only=False):
    live = []
    for pid, base in pid_map.items():
        if chrome_only and not _chrome_like(base):
            continue
        if _proc_stat(pid) and _proc_stat(pid) != "Z":
            live.append(pid)
    return sorted(live)


def _reap(chrome_only=True):
    pids = _alive_pids(_state["pids"], chrome_only)
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    deadline = time.time() + 2.0
    while time.time() < deadline and _alive_pids(_state["pids"], chrome_only):
        time.sleep(0.1)
    stubborn = _alive_pids(_state["pids"], chrome_only)
    for pid in stubborn:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    deadline = time.time() + 1.0
    while time.time() < deadline and _alive_pids(_state["pids"], chrome_only):
        time.sleep(0.1)
    survivors = _alive_pids(_state["pids"], chrome_only)
    return {"sigterm": len(pids), "sigkill": len(stubborn),
            "survivors": survivors}


async def _launch_pw():
    from patchright.async_api import async_playwright
    if _state["pw"] is None:
        _state["pw"] = await async_playwright().start()
    return _state["pw"]


async def _launch():
    if _state["browser"] is not None and _state["browser"].is_connected():
        return _state["browser"]
    pw = await _launch_pw()
    def _bundled():
        try:
            cand = pw.chromium.executable_path
        except Exception:
            return None
        return cand if cand and os.path.exists(cand) else None
    exe = (os.environ.get(EXE_ENV, "") or "").strip()
    attempts = []
    bundled = _bundled()
    if bundled:
        attempts += [{"executable_path": bundled}, {"executable_path": bundled, "args": ["--no-sandbox"]}]
    if exe:
        attempts += [{"executable_path": exe}, {"executable_path": exe, "args": ["--no-sandbox"]}]
    if os.path.exists("/usr/bin/chromium"):
        attempts += [{"executable_path": "/usr/bin/chromium"},
                     {"executable_path": "/usr/bin/chromium", "args": ["--no-sandbox"]}]
    attempts += [{}, {"args": ["--no-sandbox"]}]
    last = None
    for kwargs in attempts:
        kwargs = {"headless": True, "timeout": LAUNCH_TIMEOUT_S * 1000, **kwargs}
        try:
            browser = await pw.chromium.launch(**kwargs)
            _state["browser"] = browser
            _record()
            return browser
        except Exception as e:
            last = e
    raise RuntimeError("chromium launch failed: %s: %s" % (type(last).__name__, last))


class BrowserError(Exception):
    pass


async def _extract_coro(url):
    browser = await _launch()
    page = await browser.new_page()
    _state["pages"] += 1
    t0 = time.time()
    try:
        resp = await page.goto(url, timeout=NAV_TIMEOUT_S * 1000,
                               wait_until="domcontentloaded")
        if resp is None:
            raise BrowserError("navigation returned no response")
        ctype = ""
        try:
            ctype = str(dict(resp.headers).get("content-type", ""))
        except Exception:
            ctype = ""
        base_type = ctype.split(";")[0].strip().lower()
        if base_type and base_type not in READABLE_TYPES:
            raise BrowserError("unsupported content-type: %s" % (base_type or ctype))
        final_url = str(page.url)
        title = str(await page.title() or "").strip()[:TITLE_LIMIT_CHARS]
        body = str(await page.inner_text("body") or "")
        text = "\n".join(ln.rstrip() for ln in body.splitlines())
        text = text.strip()[:TEXT_LIMIT_CHARS]
        pairs = []
        try:
            pairs = await page.eval_on_selector_all(
                "a", "els => els.map(e => [e.href, (e.innerText || '').trim()])")
        except Exception:
            pairs = []
        links, seen = [], set()
        for href, ltext in pairs or []:
            if not isinstance(href, str) or not href.startswith(("http://", "https://")):
                continue
            if href in seen:
                continue
            seen.add(href)
            links.append({"href": href[:TITLE_LIMIT_CHARS],
                          "text": str(ltext or "")[:LINK_TEXT_LIMIT]})
            if len(links) >= LINK_LIMIT:
                break
        return {"url": url, "title": title, "text": text, "url_final": final_url,
                "elapsed_s": round(time.time() - t0, 3), "links": links,
                "status": int(getattr(resp, "status", 0) or 0)}
    finally:
        try:
            await page.close()
        finally:
            _state["pages"] = max(0, _state["pages"] - 1)


async def _close_browser_coro():
    browser = _state["browser"]
    if browser is not None:
        _state["browser"] = None
        try:
            await browser.close()
        except Exception:
            pass


async def _teardown_coro():
    browser = _state["browser"]
    _state["browser"] = None
    if browser is not None:
        try:
            await browser.close()
        except Exception:
            pass
    pw = _state["pw"]
    _state["pw"] = None
    if pw is not None:
        try:
            await pw.stop()
        except Exception:
            pass
    _state["pages"] = 0


def _scheme_ok(url):
    return isinstance(url, str) and url.lower().startswith(("http://", "https://"))


def tool_browser_open(a):
    args = a or {}
    url = str(args.get("url", "") or "").strip()
    if not _scheme_ok(url):
        return {"error": "browser_open needs an http(s) url"}
    try:
        return _call(_extract_coro(url), CALL_TIMEOUT_S)
    except BrowserError as e:
        return {"error": str(e), "url": url}
    except Exception as e:
        return {"error": "%s: %s" % (type(e).__name__, e), "url": url}


def tool_browser_close(a):
    _record()
    if _state["browser"] is None and _state["pw"] is None:
        return {"closed": True, "cold": True, "pages_open": 0, "reaped": {"sigterm": 0, "sigkill": 0, "survivors": []}}
    try:
        _call(_close_browser_coro(), CLOSE_TIMEOUT_S)
    except Exception:
        pass
    reaped = _reap(chrome_only=True)
    _record()
    return {"closed": True, "cold": False, "pages_open": 0, "reaped": reaped}


def tool_browser_health(a):
    return {"browser": "ready" if _state["browser"] is not None else "cold",
            "pages_open": _state["pages"]}


def _teardown():
    if _loop is None:
        _state["pw"] = None
        _state["browser"] = None
        _record()
        _reap(chrome_only=True)
        return
    try:
        _call(_teardown_coro(), CLOSE_TIMEOUT_S)
    except Exception:
        pass
    try:
        _record()
        _reap(chrome_only=True)
    except Exception:
        pass


TOOLS = [
    ("browser_open", "Read ONE web page in a real headless chromium: follow redirects, return {title, text (body text, max 8000 chars), url_final, elapsed_s, links (top 20 href+text), status}. Fails honestly with {error} on net errors, unsupported content types or launch problems; never fabricates missing content. http(s) urls only.",
     {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}),
    ("browser_close", "Free the shared browser opened by browser_open. Idempotent; safe on a cold server.",
     {"type": "object", "properties": {}, "required": []}),
    ("browser_health", "Browser lane state without launching anything on a cold server: {browser: ready|cold, pages_open}.",
     {"type": "object", "properties": {}, "required": []}),
]

TOOLS_DEF = [{"name": n, "description": d, "inputSchema": s} for n, d, s in TOOLS]
_DISPATCH = {"browser_open": tool_browser_open, "browser_close": tool_browser_close,
             "browser_health": tool_browser_health}


def dispatch(name, a):
    if name not in _DISPATCH:
        raise KeyError(name)
    return _DISPATCH[name](a or {})


def respond(w, id, res=None, err=None):
    if id is None:
        return
    out = {"jsonrpc": "2.0", "id": id, "result": res} if err is None else {"jsonrpc": "2.0", "id": id, "error": err}
    w.write(json.dumps(out, ensure_ascii=False) + "\n")
    w.flush()


def main():
    atexit.register(_teardown)

    def _on_term(signum, frame):
        _teardown()
        raise SystemExit(0)

    try:
        signal.signal(signal.SIGTERM, _on_term)
    except (ValueError, OSError):
        pass
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
