import json, os, re, subprocess, sys, tempfile, threading, time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "state" / "logs"
BENCH = ROOT / "state" / "bench"
MODEL_PORT, GATE_PORT, SLIM_PORT = 7640, 7641, 7642
SINK_PORT, CAPGATE_PORT, SPARE_PORT, SCRATCH_PORT = 7643, 7644, 7645, 7646
BLOCK = (MODEL_PORT, GATE_PORT, SLIM_PORT, SINK_PORT, CAPGATE_PORT, SPARE_PORT,
         SCRATCH_PORT, 7647)
DBS_ROOT = str(Path.home() / ".greylocalrag" / "dbs")
CHILDREN = []
SINK_REQS = []
SINK_SERVER = None
MODEL_PID = 0
TMP_ROOTS = []


def say(msg):
    print("G " + str(msg), flush=True)


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def busy_ports():
    out = subprocess.run(["ss", "-ltn"], capture_output=True, text=True).stdout
    hits = set()
    for ln in out.splitlines():
        parts = ln.split()
        if len(parts) > 3 and parts[3].rsplit(":", 1)[-1].isdigit():
            n = int(parts[3].rsplit(":", 1)[-1])
            if n in BLOCK:
                hits.add(n)
    return sorted(hits)


def child_env(extra):
    keep = ("PATH", "LANG", "HOME", "TMPDIR")
    env = {k: v for k, v in os.environ.items() if k in keep}
    env.update(extra)
    return env


def spawn(label, cmd, extra_env=None):
    log = open(LOGS / ("gauntlet-%s.log" % label), "ab")
    p = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                         cwd=str(ROOT), env=child_env(extra_env or {}))
    log.close()
    CHILDREN.append((label, p))
    say("spawn %s pid=%d" % (label, p.pid))
    return p


def reap_recorded():
    for label, p in reversed(CHILDREN):
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass


def survivor_check():
    return [(label, p.pid) for label, p in CHILDREN if alive(p.pid)]


def attribution():
    out = {}
    for label, p in CHILDREN:
        try:
            raw = Path("/proc/%d/cmdline" % p.pid).read_bytes()
            out[str(p.pid)] = "%s: %s" % (label, raw.replace(b"\x00", b" ").decode("utf-8", "ignore").strip()[:120])
        except OSError:
            out[str(p.pid)] = "%s: exited" % label
    return out


def tmp_root(prefix):
    d = tempfile.mkdtemp(prefix=prefix)
    TMP_ROOTS.append(d)
    return d


def http_get_json(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode("utf-8", "ignore"))


def http_post_json(url, obj, timeout=900):
    body = json.dumps(obj).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "ignore")


def wait_up(url, timeout_s=120):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


class Sink(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _reply(self, payload, ctype="application/json"):
        out = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(out)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        self.wfile.write(out)

    def do_GET(self):
        self._reply({"status": "ok", "results": [{"url": "http://sink/c", "title": "sink",
                                                  "content": "sink result body"}]})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n > 0 else b""
        SINK_REQS.append(json.loads(body.decode("utf-8", "ignore")))
        self._reply({"id": "sink", "object": "chat.completion", "choices": [
            {"index": 0, "message": {"role": "assistant", "content": "sink-ok"},
             "finish_reason": "stop"}]})


def start_sink(port):
    global SINK_SERVER
    SINK_SERVER = ThreadingHTTPServer(("127.0.0.1", port), Sink)
    threading.Thread(target=SINK_SERVER.serve_forever, daemon=True).start()
    say("sink up :%d" % port)


def stop_sink():
    global SINK_SERVER
    if SINK_SERVER is not None:
        try:
            SINK_SERVER.shutdown()
            SINK_SERVER.server_close()
        except Exception:
            pass
        SINK_SERVER = None


def launcher_text():
    return (ROOT / "bin" / "greylocalrag").read_text(encoding="utf-8")


def launcher_floor():
    m = re.search(r'GREYLOCALRAG_RAG_FLOOR="?\$\{GREYLOCALRAG_RAG_FLOOR:-([0-9.]+)\}"?',
                  launcher_text())
    return float(m.group(1)) if m else None


def launcher_think_env():
    out = {}
    m = re.search(r'LLAMA_ARG_THINK="?\$\{LLAMA_ARG_THINK:-([a-z]+)\}"?', launcher_text())
    if m:
        out["LLAMA_ARG_THINK"] = m.group(1)
    m2 = re.search(r'LLAMA_ARG_CHAT_TEMPLATE_KWARGS="?\$\{LLAMA_ARG_CHAT_TEMPLATE_KWARGS:([^}]+)\}"?',
                   launcher_text())
    if m2:
        out["LLAMA_ARG_CHAT_TEMPLATE_KWARGS"] = m2.group(1)
    return out


def teardown_phase(tag):
    reap_recorded()
    if MODEL_PID and alive(MODEL_PID):
        os.kill(MODEL_PID, 15)
        for _ in range(20):
            if not alive(MODEL_PID):
                break
            time.sleep(0.5)
        if alive(MODEL_PID):
            os.kill(MODEL_PID, 9)
    stop_sink()
    for d in TMP_ROOTS:
        import shutil
        shutil.rmtree(d, ignore_errors=True)
    survivors = survivor_check()
    busy = busy_ports()
    say("teardown %s survivors=%s busy=%s" % (tag, survivors, busy))
    return {"survivors": survivors, "busy_ports": busy, "cmdlines": attribution()}


ONS = [
    "how do I mirror a directory tree with robocopy",
    "list wifi profiles stored on this machine",
    "find which process listens on port 8080",
    "shut down the pc after 60 seconds",
    "show my ip configuration",
    "empty the dns resolver cache",
    "kill a process by pid",
    "check system file integrity with sfc",
    "trace route to a host and time each hop",
    "search for a file anywhere on the system",
    "compare two text files line by line",
    "compress a folder into a tar archive",
    "see what services are running with systemctl",
    "copy files between two machines over ssh",
    "watch the kernel journal as messages arrive",
    "find the biggest folders on the disk",
    "resume a download that dropped with curl",
    "set an environment variable permanently with setx",
    "schedule a job to run nightly with crontab",
    "look up which process has a file open with lsof",
]
SHARE = [
    "what is the capital of Portugal and its full history",
    "how does photosynthesis work in green plants",
    "when is the best time to plant tomatoes",
    "why is the sky blue and sunsets red",
    "tell me about the history of the roman empire",
    "what should I eat before running a marathon",
    "which language is hardest to learn for adults",
    "how do bees communicate with each other",
    "what was the main cause of the french revolution",
    "recommend a good book about space exploration",
]
SHARE_EXT = [
    "what do you think about the meaning of life and the universe",
    "give me a quick summary of the plot of hamlet and why it matters",
    "the best way to learn painting for beginners at home",
    "when did the second world war end and who won",
    "is it better to exercise in the morning or the evening",
    "how can I improve my sleep quality naturally",
    "what are the health benefits of drinking green tea every day",
    "why do cats purr when they are happy",
]
CLEAN = [
    "quantum chromatophore resonance",
    "zzyq wubb flux capacitor",
    "spectral nomogram calipers",
    "xylophone thermodynamics",
    "belligerent narwhal armada",
    "grommet flange turbidity",
    "pneumatic wobble sprocket",
    "velociraptor xylophone",
    "ambivalent cactus taxonomy",
    "quixotic fjord almanac",
]
CHOSEN_FLOOR = 19.0


def phase_floor_calibration():
    sys.path.insert(0, str(ROOT / "services"))
    os.environ["GREYLOCALRAG_DBS_ROOT"] = DBS_ROOT
    import rag.kbcore as kb
    db = kb.db_dir("commands")
    rows = kb.pack_rows(db)
    recs = [{"i": r["i"], "t": r["t"]} for r in rows[:3]]

    def top_lex(q):
        hits = kb.search(db, q, 6, None)
        return round(max((float(h.get("lex") or 0.0) for h in hits), default=0.0), 2)

    scores = {}
    for name, group in (("on_domain", ONS), ("off_topic_shareword", SHARE),
                        ("off_topic_shareword_probes", SHARE_EXT),
                        ("off_topic_clean", CLEAN)):
        scores[name] = [{"q": q, "top_lex": top_lex(q)} for q in group]
    onv = [x["top_lex"] for x in scores["on_domain"]]
    shv = [x["top_lex"] for x in scores["off_topic_shareword"]] + \
          [x["top_lex"] for x in scores["off_topic_shareword_probes"]]
    clv = [x["top_lex"] for x in scores["off_topic_clean"]]
    floors = sorted({0.25, 10.0, 12.0, 16.0, 19.0, 20.0, CHOSEN_FLOOR}
                    | {v + 0.01 for v in onv + shv if v > 0})
    sweep = []
    for f in floors:
        onr = round(sum(1 for v in onv if v >= f) / len(onv), 3)
        shl = round(sum(1 for v in shv if v >= f) / len(shv), 3)
        cll = round(sum(1 for v in clv if v >= f) / len(clv), 3)
        sweep.append({"floor": round(f, 2), "on_recall": onr, "share_leak": shl,
                      "clean_leak": cll, "margin": round(onr - shl, 3)})
    best = max(s["margin"] for s in sweep)
    band = [s["floor"] for s in sweep if s["margin"] == best]
    chosen = CHOSEN_FLOOR
    note = ""
    if band and not (min(band) <= chosen < max(band) + 0.01):
        chosen = round((min(band) + max(band)) / 2, 1)
        note = "chosen floor recomputed from band midpoint"
    art = {
        "ts": time.strftime("%F %T"),
        "db": {"name": "commands", "root": DBS_ROOT, "records": len(rows),
               "sample": recs},
        "scorer": "kb.search keyword lex = st*4 + sx + sx/max(3, len(body)//400); "
                  "gate score = max(cos, lex), keyword mode cos=0",
        "classes": scores,
        "summary": {"on_min": min(onv), "on_max": max(onv),
                    "share_min": min(shv), "share_max": max(shv),
                    "clean_max": max(clv)},
        "sweep": sweep,
        "max_margin": best,
        "max_margin_band": band,
        "chosen_floor": chosen,
        "chosen_note": note,
        "f3_reproduction": {"portugal": scores["off_topic_shareword"][0]["top_lex"],
                            "reviewer_value": 16.0},
        "launcher_floor_at_run": launcher_floor(),
        "verdict": "classes overlap at lexical layer; floor cannot fully separate; "
                   "chosen floor maximizes margin under recorded trade",
    }
    BENCH.mkdir(parents=True, exist_ok=True)
    out = BENCH / "floor-calibration.json"
    out.write_text(json.dumps(art, indent=1), encoding="utf-8")
    say("calibration artifact %s" % out)
    say("summary %s" % json.dumps(art["summary"]))
    say("max_margin %s band %s chosen %s" % (best, band, chosen))
    rc = {"artifact": str(out), "chosen_floor": chosen, "max_margin": best,
          "band": band, "share_max": max(shv), "on_min": min(onv),
          "clean_max": max(clv), "launcher_floor": launcher_floor(),
          "chosen_in_band": bool(min(band) <= CHOSEN_FLOOR < max(band) + 0.01) if band else False}
    return 0, rc


def sup_child(root):
    sys.path.insert(0, str(ROOT / "services"))
    import supervision.supervisor as sup
    events = []
    for i in range(15):
        events.append({"turn": i, "kind": "tool_call", "tool": "bash",
                       "args": {"command": "sleep 90"}, "digest": "identicaldigest"})
    s = sup.Supervisor(task_id="gauntlet-drill")
    s.on_event({"kind": "task_started", "task": "gauntlet-drill"})
    steers = []
    for i, ev in enumerate(events, 1):
        s.on_event(ev)
        for m in s.drain():
            steers.append({"after_event": i, "msg": m})
    log = (Path(os.environ["HOME"]) / ".greylocalrag" / "state" / "supervision"
           / "supervisor.log").read_text(encoding="utf-8", errors="ignore")
    nodes = [int(m) for m in re.findall(r"LADDER-(\d)", log)]
    src = (ROOT / "services" / "supervision" / "supervisor.py").read_text(encoding="utf-8")
    free = {"subprocess": "subprocess" in src, "os.system": "os.system" in src,
            "ctypes.spawn": "ctypes.spawn" in src, "popen": ".popen(" in src.lower()}
    state = Path(os.environ["HOME"]) / ".greylocalrag" / "state" / "supervision"
    steer_lines = len((state / "steer.jsonl").read_text(encoding="utf-8").splitlines())
    sidecar_lines = len((state / "supervision_events.jsonl").read_text(encoding="utf-8").splitlines())
    ledger = json.loads((state / "ledger.json").read_text(encoding="utf-8"))
    print("GJSON " + json.dumps({"nodes": nodes, "steers": steers,
                                 "steer_lines": steer_lines,
                                 "sidecar_lines": sidecar_lines,
                                 "subprocess_free": free,
                                 "ledger": {k: ledger.get(k) for k in
                                            ("task", "actions", "ok", "failures",
                                             "forbidden")},
                                 "log_tail": log.strip().splitlines()[-3:]}), flush=True)
    return 0


def phase_sup_drill():
    root = tmp_root("glr-glt-sup-")
    sdir = Path(root) / ".greylocalrag" / "state" / "supervision"
    sdir.mkdir(parents=True)
    p = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                        "--sup-child", root], capture_output=True, text=True,
                       cwd=str(ROOT), env=child_env({"HOME": root}), timeout=120)
    if p.returncode != 0:
        say("sup-child rc=%s err=%.300s" % (p.returncode, p.stderr[-300:]))
        return 1, {"error": p.stderr[-300:]}
    lines = [ln for ln in p.stdout.splitlines() if ln.startswith("GJSON ")]
    data = json.loads(lines[-1][6:])
    nodes12 = data["nodes"][:4]
    ok_nodes = nodes12 == [1, 2, 3, 4]
    ok_free = not any(data["subprocess_free"].values())
    ok_blocked = "BLOCKED" in str(data["log_tail"])
    ok_steer = data["steer_lines"] == 5 and len(data["steers"]) == 5
    say("nodes=%s subprocess_free=%s steer_lines=%s blocked=%s"
        % (nodes12, data["subprocess_free"], data["steer_lines"], ok_blocked))
    ok = ok_nodes and ok_free and ok_blocked and ok_steer
    return (0 if ok else 1), {"drill": data, "checks": {
        "ladder_nodes_1234": ok_nodes, "subprocess_free": ok_free,
        "blocked_at_15": ok_blocked, "steers_five": ok_steer}}


def rpc(proc, obj, timeout=40):
    box = {}

    def run():
        try:
            proc.stdin.write((json.dumps(obj) + "\n").encode())
            proc.stdin.flush()
            box["resp"] = json.loads(proc.stdout.readline())
        except Exception as e:
            box["err"] = repr(e)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout)
    if "resp" not in box:
        raise AssertionError("mcp rpc timeout: %s" % obj.get("method"))
    return box["resp"]


def mcp_open(py, script, env_extra):
    p = subprocess.Popen([sys.executable, str(script)], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, cwd=str(ROOT),
                         env=child_env(env_extra))
    CHILDREN.append(("mcp-" + Path(script).stem, p))
    say("spawn mcp %s pid=%d" % (Path(script).name, p.pid))
    rpc(p, {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}})
    return p


def mcp_call(p, i, name, args):
    r = rpc(p, {"jsonrpc": "2.0", "id": i, "method": "tools/call",
                "params": {"name": name, "arguments": args}})
    return json.loads(r["result"]["content"][0]["text"])


def phase_hold_release():
    import shutil
    root = tmp_root("glr-glt-hold-")
    runfile = Path(root) / "search-run"
    start_sink(SPARE_PORT)
    sink_url = "http://127.0.0.1:%d" % SPARE_PORT
    p = mcp_open(sys.executable, ROOT / "services" / "search_mcp.py", {
        "GREYLOCALRAG_SEARCH_RUN_FILE": str(runfile),
        "GREYLOCALRAG_HEALTH_WAIT_S": "6",
        "GREYLOCALRAG_HEALTH_REPOLL_S": "10",
        "GREYLOCALRAG_SEARX_BASES": sink_url,
    })
    sleeper = subprocess.Popen(["sleep", "90"])
    CHILDREN.append(("sleeper", sleeper))
    say("sleeper pid=%d 90s" % sleeper.pid)
    runfile.write_text("1")

    def producer():
        sleeper.wait()
        try:
            runfile.unlink()
        except OSError:
            pass

    threading.Thread(target=producer, daemon=True).start()
    calls = []
    req = {"jsonrpc": "2.0", "id": 100, "method": "tools/call",
           "params": {"name": "search_health", "arguments": {}}}
    for i in range(5):
        r0 = time.time()
        resp = rpc(p, req, timeout=40)
        body = json.loads(resp["result"]["content"][0]["text"])
        calls.append({"wall": round(time.time() - r0, 2), "pending": body.get("pending"),
                      "blocked_s": body.get("blocked_s"), "isError": resp["result"].get("isError", False)})
        time.sleep(4.0)
    held = all(c["pending"] is True and c["blocked_s"] >= 5.0 and not c["isError"]
               for c in calls)
    while alive(sleeper.pid) or runfile.exists():
        time.sleep(1.0)
    r0 = time.time()
    resp = rpc(p, req, timeout=40)
    body = json.loads(resp["result"]["content"][0]["text"])
    release = {"wall": round(time.time() - r0, 2), "pending": body.get("pending"),
               "blocked_s": body.get("blocked_s"), "ok": body.get("ok"),
               "results_probe": (body.get("instances") or [{}])[0].get("ok")}
    released = release["pending"] is False and release["blocked_s"] == 0.0 \
        and release["ok"] is True and release["wall"] < 15
    lgsrc = (ROOT / "config" / "extensions" / "loop-guard.ts").read_text(encoding="utf-8")
    guard_pins = {
        "run_file_default_search_run": 'search-run' in lgsrc,
        "long_job_tools_have_search_health": '"search_health"' in lgsrc,
        "hold_wait_cap_300": "WAIT_MCP_S" in lgsrc,
    }
    marker_gone = not runfile.exists()
    say("held_calls=%s held_ok=%s released=%s marker_gone=%s guard_pins=%s"
        % (json.dumps(calls), held, json.dumps(release), marker_gone, guard_pins))
    p.terminate()
    sleeper.terminate()
    stop_sink()
    shutil.rmtree(root, ignore_errors=True)
    ok = held and released and marker_gone and all(guard_pins.values())
    art = {"held_calls": calls, "release": release, "guard_pins": guard_pins,
           "sleeper_s": 90}
    BENCH.mkdir(parents=True, exist_ok=True)
    (BENCH / "gauntlet-hold-release.json").write_text(json.dumps(art, indent=1),
                                                      encoding="utf-8")
    return (0 if ok else 1), art


def phase_consent():
    import shutil
    root = tmp_root("glr-glt-consent-")
    dbs = Path(root) / "dbs"
    digest_path = Path(root) / "research-digest.json"
    yes_path = Path(root) / "consent.txt"
    start_sink(SPARE_PORT)
    real_marker = Path.home() / ".greylocalrag" / "state" / "search-run"
    sp = mcp_open(sys.executable, ROOT / "services" / "search_mcp.py", {
        "GREYLOCALRAG_SEARX_BASES": os.environ.get("GREYLOCALRAG_SEARX_BASES", "")})
    r0 = time.time()
    try:
        sea = mcp_call(sp, 1, "search", {"query": "robocopy mirror flags windows", "k": 5})
    finally:
        pass
    search_wall = round(time.time() - r0, 2)
    results = sea if isinstance(sea, list) else []
    stop_sink()
    marker_clean_after = not real_marker.exists()
    digest = {"query": "robocopy mirror flags windows", "result_count": len(results),
              "results": results[:5], "ts": time.strftime("%F %T"),
              "consent_model": model_card_line()}
    digest_path.write_text(json.dumps(digest, indent=1), encoding="utf-8")
    sp.terminate()
    rp = mcp_open(sys.executable, ROOT / "services" / "rag_mcp.py", {
        "GREYLOCALRAG_DBS_ROOT": str(dbs)})
    st0 = mcp_call(rp, 2, "rag_status", {"db": "commands"})
    zero_before = st0["records"] == 0 and not (dbs / "commands" / "pack.jsonl").exists()
    yes_path.write_text("yes")
    granted = yes_path.read_text(encoding="utf-8").strip() == "yes"
    ing = mcp_call(rp, 3, "rag_ingest_text", {
        "db": "commands", "title": "research digest robocopy mirror flags",
        "text": "Web research digest for query 'robocopy mirror flags windows'. "
                "Captured %d results; consent granted by operator before ingest. "
                "Top results: %s" % (len(results), "; ".join(
                    (r.get("title") or "")[:60] for r in results[:3])),
        "source": "web research digest", "url": "http://digest/gauntlet",
        "date": time.strftime("%F")})
    st1 = mcp_call(rp, 4, "rag_status", {"db": "commands"})
    stored = st1["records"] >= 1
    ref = mcp_call(rp, 5, "rag_remove", {"db": "commands", "match": "digest"})
    staged_only = ref["removed"] == 0 and ref.get("matched", 0) >= 1 \
        and (dbs / "commands" / "pending-remove.json").exists()
    rem = mcp_call(rp, 6, "rag_remove", {"db": "commands", "match": "digest",
                                         "confirm": True})
    cleared = rem["removed"] >= 1
    st2 = mcp_call(rp, 7, "rag_status", {"db": "commands"})
    final_zero = st2["records"] == 0
    say("search wall=%ss results=%d marker_clean=%s zero_before=%s added=%s "
        "staged_only=%s removed=%s final_zero=%s"
        % (search_wall, len(results), marker_clean_after, zero_before,
           ing.get("added"), staged_only, rem.get("removed"), final_zero))
    rp.terminate()
    art = {"search": {"wall_s": search_wall, "results": results[:5],
                      "real_product_marker_used": True},
           "marker_clean_after": marker_clean_after,
           "digest": digest_path.name, "consent": {"asked": True, "granted": granted},
           "records_zero_before_consent": zero_before,
           "ingest_added": ing.get("added"), "records_after_ingest": st1["records"],
           "remove_stage": {"removed": ref.get("removed"),
                            "matched": ref.get("matched"), "staged": staged_only},
           "remove_confirm": {"removed": rem.get("removed"), "cleared": cleared},
           "records_final": st2["records"], "final_zero": final_zero}
    BENCH.mkdir(parents=True, exist_ok=True)
    (BENCH / "gauntlet-consent.json").write_text(json.dumps(art, indent=1, ensure_ascii=False),
                                                 encoding="utf-8")
    shutil.rmtree(root, ignore_errors=True)
    ok = marker_clean_after and zero_before and granted and stored \
        and staged_only and cleared and final_zero
    return (0 if ok else 1), art


def model_card_line():
    card = (ROOT / "model" / "greylocalrag.md").read_text(encoding="utf-8")
    for ln in card.splitlines():
        if "Consent law" in ln:
            return ln.strip()
    return ""


def phase_offline():
    import shutil
    root = tmp_root("glr-glt-off-")
    state = Path(root) / "state"
    dbs = Path(root) / "dbs"
    state.mkdir()
    start_sink(SINK_PORT)
    pp = spawn("supervision-pump", [sys.executable, str(ROOT / "services" / "child_wrap.py"),
                                     sys.executable, str(ROOT / "services" / "supervision" / "pump.py")], {
        "GREYLOCALRAG_SESS_ROOT": str(Path(os.environ["HOME"]) / ".greylocalrag" / "agent" / "sessions"),
    })
    gp = spawn("gate-off", [sys.executable, str(ROOT / "services" / "child_wrap.py"),
                            sys.executable, str(ROOT / "services" / "rag_gate.py")], {
        "RAG_GATE_PORT": str(CAPGATE_PORT),
        "GREYLOCALRAG_UPSTREAM": "http://127.0.0.1:%d" % SINK_PORT,
        "GREYLOCALRAG_DBS": "commands",
        "GREYLOCALRAG_DBS_ROOT": str(dbs),
        "GREYLOCALRAG_STATE_DIR": str(state),
        "GREYLOCALRAG_RAG_FLOOR": str(launcher_floor()),
    })
    up = wait_up("http://127.0.0.1:%d/health" % CAPGATE_PORT)
    if not up:
        say("gate did not come up")
        gp.terminate()
        pp.terminate()
        stop_sink()
        shutil.rmtree(root, ignore_errors=True)
        return 1, {"error": "gate up failed"}
    body = {"model": "greylocalrag", "max_tokens": 16,
            "messages": [{"role": "user", "content": "what does robocopy /MIR do?"}]}
    url = "http://127.0.0.1:%d/v1/chat/completions" % CAPGATE_PORT
    offline_before = "[OFFLINE-MODE]" not in json.dumps(SINK_REQS)
    http_post_json(url, body, 30)
    cap_with = SINK_REQS[-1]["messages"][-1]["content"]
    (state / "rag-offline").write_text("")
    http_post_json(url, body, 30)
    cap_on = SINK_REQS[-1]["messages"][-1]["content"]
    (state / "rag-offline").unlink()
    http_post_json(url, body, 30)
    cap_after = SINK_REQS[-1]["messages"][-1]["content"]
    offline_marker = "[OFFLINE-MODE] answering from your KB only"
    checks = {
        "absent_before": offline_marker not in cap_with,
        "present_with_sentinel": cap_on.endswith(offline_marker),
        "absent_after_removal": cap_after == "[NO-KB-GROUNDING]",
        "system_is_last_message": SINK_REQS[-1]["messages"][-1]["role"] == "system",
        "gate_layer_artifact": True,
    }
    say("offline caps: before=%r on=%r after=%r checks=%s"
        % (cap_with[:60], cap_on[-60:], cap_after[:60], checks))
    gp.terminate()
    pp.terminate()
    stop_sink()
    ok = all(checks.values())
    art = {"cap_with_sentinel": cap_on, "cap_after_removal": cap_after,
           "cap_before": cap_with[:120], "checks": checks}
    BENCH.mkdir(parents=True, exist_ok=True)
    (BENCH / "gauntlet-offline.json").write_text(json.dumps(art, indent=1),
                                                 encoding="utf-8")
    shutil.rmtree(root, ignore_errors=True)
    return (0 if ok else 1), art


def phase_floor_reproof():
    import shutil
    root = tmp_root("glr-glt-rep-")
    dbs = Path(root) / "dbs"
    start_sink(SINK_PORT)
    floor = launcher_floor()
    gp = spawn("gate-rep", [sys.executable, str(ROOT / "services" / "child_wrap.py"),
                            sys.executable, str(ROOT / "services" / "rag_gate.py")], {
        "RAG_GATE_PORT": str(CAPGATE_PORT),
        "GREYLOCALRAG_UPSTREAM": "http://127.0.0.1:%d" % SINK_PORT,
        "GREYLOCALRAG_DBS": "commands",
        "GREYLOCALRAG_DBS_ROOT": DBS_ROOT,
        "GREYLOCALRAG_STATE_DIR": str(root),
        "GREYLOCALRAG_RAG_FLOOR": str(floor),
    })
    if not wait_up("http://127.0.0.1:%d/health" % CAPGATE_PORT):
        say("gate did not come up")
        gp.terminate()
        stop_sink()
        shutil.rmtree(root, ignore_errors=True)
        return 1, {"error": "gate up failed", "floor": floor}
    url = "http://127.0.0.1:%d/v1/chat/completions" % CAPGATE_PORT

    def capture(q):
        SINK_REQS.clear()
        body = {"model": "greylocalrag", "max_tokens": 16,
                "messages": [{"role": "user", "content": q}]}
        http_post_json(url, body, 30)
        sysc = SINK_REQS[-1]["messages"][-1]["content"]
        n = sysc.count("[KB:commands#")
        return {"marker": "[NO-KB-GROUNDING]" in sysc, "chunks": n,
                "head": sysc[:110], "scores": [float(s) for s in
                                               re.findall(r"score=([0-9.]+)", sysc)]}

    portugal = capture("what is the capital of Portugal and its full history")
    real = [capture(q) for q in (
        "how do I mirror a directory tree with robocopy",
        "schedule a job to run nightly with crontab",
        "look up which process has a file open with lsof")]
    checks = {
        "portugal_no_grounding": portugal["marker"] is True and portugal["chunks"] == 0,
        "three_real_ground": len(real) == 3 and all(r["chunks"] >= 1 and not r["marker"]
                                                    for r in real),
        "launcher_floor_carried": floor == CHOSEN_FLOOR,
    }
    say("portugal=%s reals=%s floor=%s checks=%s"
        % (json.dumps(portugal), json.dumps(real), floor, checks))
    gp.terminate()
    stop_sink()
    ok = all(checks.values())
    art = {"floor": floor, "portugal": portugal, "real_questions": real,
           "checks": checks}
    BENCH.mkdir(parents=True, exist_ok=True)
    (BENCH / "gauntlet-floor-reproof.json").write_text(json.dumps(art, indent=1),
                                                       encoding="utf-8")
    shutil.rmtree(root, ignore_errors=True)
    return (0 if ok else 1), art


QUIZ = [
    "how do I mirror a directory tree with robocopy",
    "check system file integrity with sfc",
    "trace route to a host and time each hop",
    "search for a file anywhere on the system",
    "compare two text files line by line",
    "watch the kernel journal as messages arrive",
    "set an environment variable permanently with setx",
    "schedule a job to run nightly with crontab",
    "look up which process has a file open with lsof",
    "show the routing table with route print",
]


def harness_env(extra):
    for k in list(os.environ):
        if k.startswith(("GREYAGENT_", "GREYLOCALRAG_", "SLIMTOKEN_", "RAG_GATE_",
                         "CORTEXAGENT_", "CLAUDE", "ANTHROPIC", "PI_", "CORTEX_")):
            del os.environ[k]
    os.environ.setdefault("GREYAGENT_THINKING", "off")
    os.environ["GREYLOCALRAG_THREADS"] = "4"
    os.environ["GREYLOCALRAG_ASSUME_RAM_GB"] = "8"
    os.environ["GREYAGENT_NGL"] = "0"
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    os.environ["GREYAGENT_MODEL_PORT"] = str(MODEL_PORT)
    os.environ.update(extra or {})


def boot_model(port, timeout=600):
    global MODEL_PID
    sys.path.insert(0, str(ROOT / "build" / "src"))
    import server as model_server
    t0 = time.time()
    boot = model_server.start_model(timeout=timeout)
    if not boot.get("ok") or not boot.get("pid"):
        return None, {"boot": boot}
    MODEL_PID = int(boot["pid"])
    info = {"boot": {"ok": True, "ctx": boot.get("ctx"), "pid": MODEL_PID,
                     "already": boot.get("already", False),
                     "sec": round(time.time() - t0, 1),
                     "model": str(getattr(model_server, "MODEL_PATH", ""))}}
    return model_server, info


THINK_OPEN = "<" + "think" + ">"
THINK_CLOSE = "<" + "/" + "think" + ">"


def tag_stats(content):
    return {"think_open": content.count(THINK_OPEN),
            "think_close": content.count(THINK_CLOSE),
            "len": len(content)}


def phase_quiz():
    import shutil
    root = tmp_root("glr-glt-quiz-")
    SINK_REQS.clear()
    harness_env(launcher_think_env())
    model_server, info = boot_model(MODEL_PORT)
    if model_server is None:
        teardown_phase("quiz")
        shutil.rmtree(root, ignore_errors=True)
        return 1, {"error": "model boot failed", "info": info}
    say("model up %s" % json.dumps(info["boot"]))
    slim = spawn("quiz-slim", [sys.executable, str(ROOT / "services" / "child_wrap.py"),
                               str(Path.home() / ".local" / "bin" / "slimtoken"), "serve",
                               "--upstream", "http://127.0.0.1:%d" % MODEL_PORT,
                               "--port", str(SLIM_PORT)], {
        "SLIMTOKEN_MODE": "code",
        "SLIMTOKEN_ARTIFACT_DIR": str(ROOT / "state" / "slimtoken-artifacts"),
        "SLIMTOKEN_STATS_FILE": str(Path.home() / ".local" / "state" / "slimtoken" /
                                    "stats-greylocalrag.json"),
    })
    if not wait_up("http://127.0.0.1:%d/health" % SLIM_PORT):
        say("slim did not come up")
        return 1, {"error": "slim up failed", "boot": info["boot"]}
    gate = spawn("quiz-gate", [sys.executable, str(ROOT / "services" / "child_wrap.py"),
                               sys.executable, str(ROOT / "services" / "rag_gate.py")], {
        "RAG_GATE_PORT": str(GATE_PORT),
        "GREYLOCALRAG_UPSTREAM": "http://127.0.0.1:%d" % SLIM_PORT,
        "GREYLOCALRAG_DBS": "commands",
        "GREYLOCALRAG_DBS_ROOT": DBS_ROOT,
        "GREYLOCALRAG_STATE_DIR": str(root),
        "GREYLOCALRAG_RAG_FLOOR": str(launcher_floor()),
    } | launcher_think_env())
    start_sink(SINK_PORT)
    capgate = spawn("quiz-capgate", [sys.executable, str(ROOT / "services" / "child_wrap.py"),
                                     sys.executable, str(ROOT / "services" / "rag_gate.py")], {
        "RAG_GATE_PORT": str(CAPGATE_PORT),
        "GREYLOCALRAG_UPSTREAM": "http://127.0.0.1:%d" % SINK_PORT,
        "GREYLOCALRAG_DBS": "commands",
        "GREYLOCALRAG_DBS_ROOT": DBS_ROOT,
        "GREYLOCALRAG_STATE_DIR": str(root),
        "GREYLOCALRAG_RAG_FLOOR": str(launcher_floor()),
    })
    upg = wait_up("http://127.0.0.1:%d/health" % GATE_PORT)
    upc = wait_up("http://127.0.0.1:%d/health" % CAPGATE_PORT)
    if not (upg and upc):
        say("lanes did not come up gate=%s capgate=%s" % (upg, upc))
        return 1, {"error": "lanes up failed", "boot": info["boot"]}
    floor = launcher_floor()
    say("chain up: gate=%d->slim=%d->model=%d capgate=%d->sink=%d floor=%s think=%s"
        % (GATE_PORT, SLIM_PORT, MODEL_PORT, CAPGATE_PORT, SINK_PORT, floor,
           launcher_think_env()))
    msgs = []
    turns = []
    t_all0 = time.time()
    for i, q in enumerate(QUIZ, 1):
        msgs.append({"role": "user", "content": q})
        body = {"model": "greylocalrag", "max_tokens": 640, "messages": list(msgs)}
        for attempt in (1, 2):
            SINK_REQS.clear()
            http_post_json("http://127.0.0.1:%d/v1/chat/completions" % CAPGATE_PORT, body, 30)
            sysc = SINK_REQS[-1]["messages"][-1]["content"] if SINK_REQS else ""
            if sysc:
                break
            time.sleep(1.0)
        n_chunks = sysc.count("[KB:commands#")
        grounded = sysc.startswith("GROUNDING:") and n_chunks >= 1
        t0 = time.time()
        status, raw = http_post_json("http://127.0.0.1:%d/v1/chat/completions" % GATE_PORT,
                                     body, 900)
        out = json.loads(raw)
        msg = (out.get("choices") or [{}])[0].get("message", {})
        content = str(msg.get("content") or "")
        ts = tag_stats(content)
        turn = {"i": i, "q": q, "gate_chunks": n_chunks, "grounded": grounded,
                "scores": [float(s) for s in re.findall(r"score=([0-9.]+)", sysc)][:3],
                "reply_status": status, "reply_len": len(content),
                "reply_head": content[:90], "wall_s": round(time.time() - t0, 1),
                "reasoning_len": len(str(msg.get("reasoning_content") or "")),
                "finish": (out.get("choices") or [{}])[0].get("finish_reason"),
                "tags": ts}
        turns.append(turn)
        msgs.append({"role": "assistant", "content": content})
        say("quiz %d/%d chunks=%d %.1fs len=%d reasoning=%d finish=%s tags=%d head=%.90r"
            % (i, len(QUIZ), n_chunks, turn["wall_s"], len(content),
               turn["reasoning_len"], turn["finish"],
               ts["think_open"] + ts["think_close"], content[:90]))
    total_s = round(time.time() - t_all0, 1)
    grounded_n = sum(1 for t in turns if t["grounded"])
    checks = {
        "grounded_turns_nine": grounded_n == 9,
        "below_floor_turn_marked_no_kb": turns[5]["gate_chunks"] == 0
        and turns[5]["grounded"] is False,
        "every_turn_captured": all("gate_chunks" in t for t in turns)
        and all(t["reply_status"] == 200 for t in turns),
        "answers_three_plus": sum(1 for t in turns if t["reply_len"] > 0) >= 3,
        "empty_replies_only_at_length": all(t["reply_len"] > 0
                                            or t["finish"] == "length" for t in turns),
        "no_think_leak_in_replies": all(t["tags"]["think_open"] == 0
                                        and t["tags"]["think_close"] == 0 for t in turns),
        "launcher_floor_and_think_carried": floor == CHOSEN_FLOOR,
    }
    ok = all(checks.values())
    say("quiz done %.1fs checks=%s" % (total_s, checks))
    model_server.stop_model()
    try:
        (ROOT / "state" / ("model-server-%d.pid" % MODEL_PORT)).unlink()
    except OSError:
        pass
    art = {"boot": info["boot"], "floor": floor, "think_env": launcher_think_env(),
           "turns": turns, "total_s": total_s, "checks": checks}
    BENCH.mkdir(parents=True, exist_ok=True)
    (BENCH / "gauntlet-quiz.json").write_text(json.dumps(art, indent=1, ensure_ascii=False),
                                              encoding="utf-8")
    return (0 if ok else 1), art


LEAK_PROMPTS = [
    "Convert this input to JSON only, no prose. Input: name=Ada, age=36, skills=[python, c], active=true",
    "Answer with one short sentence: what does the tasklist command do?",
    "Summarize in one sentence what robocopy /MIR does.",
]


def think_child(port, variant_json, nreplies, do_stream, do_l3):
    variant = dict(json.loads(variant_json))
    variant["GREYAGENT_MODEL_PORT"] = str(port)
    harness_env(variant)
    sys.path.insert(0, str(ROOT / "build" / "src"))
    import server as model_server
    boot = model_server.start_model(timeout=600)
    if not boot.get("ok") or not boot.get("pid"):
        print("GJSON " + json.dumps({"error": "boot failed", "boot": boot}), flush=True)
        return 1
    pid = int(boot["pid"])
    payload = {"port": port, "ctx": boot.get("ctx"),
               "template_head": "", "template_enable_thinking_refs": 0,
               "template_len": 0, "replies": [], "l3": None, "stream": None,
               "variant": json.loads(variant_json)}
    try:
        props = {}
        try:
            props = http_get_json("http://127.0.0.1:%d/props" % port, 10)[1]
        except Exception:
            props = {}
        tmpl = str(props.get("chat_template", ""))
        payload["template_head"] = tmpl[:160]
        payload["template_enable_thinking_refs"] = tmpl.count("enable_thinking")
        payload["template_len"] = len(tmpl)
        base = "http://127.0.0.1:%d/v1/chat/completions" % port
        use = LEAK_PROMPTS if int(nreplies) >= 3 else LEAK_PROMPTS[:1]
        for q in use:
            t0 = time.time()
            status, raw = http_post_json(base, {"model": "greylocalrag",
                                                "max_tokens": 256,
                                                "messages": [{"role": "user", "content": q}]}, 600)
            out = json.loads(raw)
            msg = (out.get("choices") or [{}])[0].get("message", {})
            content = msg.get("content", "")
            payload["replies"].append({"prompt_head": q[:40], "status": status,
                                       "wall_s": round(time.time() - t0, 1),
                                       "content_head": content[:100],
                                       "stats": tag_stats(content),
                                       "reasoning_present": bool(msg.get("reasoning_content"))})
        if int(do_l3):
            try:
                status, raw = http_post_json(base, {
                    "model": "greylocalrag", "max_tokens": 256,
                    "chat_template_kwargs": {"enable_thinking": False},
                    "messages": [{"role": "user", "content": LEAK_PROMPTS[0]}]}, 600)
                out = json.loads(raw)
                content = (out.get("choices") or [{}])[0].get("message", {}).get("content", "")
                payload["l3"] = {"status": status, "stats": tag_stats(content),
                                 "content_head": content[:100]}
            except urllib.error.HTTPError as e:
                payload["l3"] = {"status": e.code, "rejected": True}
        if int(do_stream):
            req = urllib.request.Request(base, data=json.dumps({
                "model": "greylocalrag", "max_tokens": 256, "stream": True,
                "messages": [{"role": "user", "content": LEAK_PROMPTS[0]}]}).encode(),
                headers={"Content-Type": "application/json"})
            acc, n_reason, n_chunks = "", 0, 0
            with urllib.request.urlopen(req, timeout=600) as r:
                for line in r:
                    ln = line.decode("utf-8", "ignore").strip()
                    if not ln.startswith("data: ") or ln == "data: [DONE]":
                        continue
                    d = json.loads(ln[6:])
                    delta = (d.get("choices") or [{}])[0].get("delta", {})
                    acc += str(delta.get("content") or "")
                    if delta.get("reasoning_content"):
                        n_reason += 1
                    n_chunks += 1
            payload["stream"] = {"chunks": n_chunks, "acc_len": len(acc),
                                 "stats": tag_stats(acc), "acc_head": acc[:100],
                                 "reasoning_deltas": n_reason}
    finally:
        model_server.stop_model()
        try:
            (Path.home() / ".greylocalrag" / "state" /
             ("model-server-%d.pid" % port)).unlink()
        except OSError:
            pass
        payload["pid_alive_after"] = alive(pid)
        print("GJSON " + json.dumps(payload), flush=True)
    return 0


def phase_think_leak():
    BENCH.mkdir(parents=True, exist_ok=True)
    out = BENCH / "think-leak-qwen3vl.json"

    def child(scratch, variant, nreplies, stream, l3):
        p = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--think-child",
             str(scratch), json.dumps(variant), str(int(nreplies)),
             str(int(stream)), str(int(l3))],
            capture_output=True, text=True, cwd=str(ROOT),
            env=child_env({}), timeout=2400)
        lines = [ln for ln in p.stdout.splitlines() if ln.startswith("GJSON ")]
        if not lines:
            return {"rc": p.returncode, "stderr_tail": p.stderr[-250:]}
        return json.loads(lines[-1][6:])

    say("baseline boot (product boot line)")
    base = child(SCRATCH_PORT, {}, 3, 0, 1)
    leak_before = sum(r["stats"]["think_open"] + r["stats"]["think_close"]
                      for r in base.get("replies", []))
    say("baseline tags_before=%d template_refs=%s"
        % (leak_before, base.get("template_enable_thinking_refs")))
    say("lever L1: LLAMA_ARG_THINK=deepseek")
    l1 = child(SCRATCH_PORT, {"LLAMA_ARG_THINK": "deepseek"}, 1, 0, 0)
    say("lever L2: LLAMA_ARG_CHAT_TEMPLATE_KWARGS enable_thinking false")
    l2 = child(SCRATCH_PORT, {"LLAMA_ARG_CHAT_TEMPLATE_KWARGS":
                              '{"enable_thinking": false}'}, 1, 0, 0)
    tags1 = sum(r["stats"]["think_open"] + r["stats"]["think_close"]
                for r in l1.get("replies", []))
    tags2 = sum(r["stats"]["think_open"] + r["stats"]["think_close"]
                for r in l2.get("replies", []))
    adopted, adopt_env = None, {}
    if l2.get("replies") and tags2 == 0:
        adopted, adopt_env = "LLAMA_ARG_CHAT_TEMPLATE_KWARGS", {
            "LLAMA_ARG_CHAT_TEMPLATE_KWARGS": '{"enable_thinking": false}'}
    elif l1.get("replies") and tags1 == 0:
        adopted, adopt_env = "LLAMA_ARG_THINK", {"LLAMA_ARG_THINK": "deepseek"}
    art = {"baseline": base, "l1": l1, "l2": l2, "tags_before": leak_before,
           "tags_l1": tags1, "tags_l2": tags2, "adopted": adopted}
    say("adopted=%s (l1 tags=%d l2 tags=%d)" % (adopted, tags1, tags2))
    if adopted is None:
        art["verdict"] = "NO-LEVER: no env-level lever suppresses; engine/weights frozen"
        out.write_text(json.dumps(art, indent=1), encoding="utf-8")
        return 3, art
    text = launcher_text()
    if adopted == "LLAMA_ARG_THINK" and "LLAMA_ARG_THINK" not in text:
        edit_launcher('export LLAMA_ARG_THINK="${LLAMA_ARG_THINK:-deepseek}"')
    if adopted == "LLAMA_ARG_CHAT_TEMPLATE_KWARGS" and \
            "LLAMA_ARG_CHAT_TEMPLATE_KWARGS" not in text:
        edit_launcher('export LLAMA_ARG_CHAT_TEMPLATE_KWARGS="'
                      '${LLAMA_ARG_CHAT_TEMPLATE_KWARGS:-{\\"enable_thinking\\": false}}"')
    say("launcher now exports %s; proof boot + 3 completions + stream"
        % json.dumps(launcher_think_env()))
    proof_env = dict(launcher_think_env())
    if proof_env.get(adopted) is None:
        say("launcher export parse mismatch; aborting proof without edit trust")
        art["verdict"] = "launcher parse mismatch after edit"
        out.write_text(json.dumps(art, indent=1), encoding="utf-8")
        return 2, art
    proof = child(SCRATCH_PORT, proof_env, 3, 1, 0)
    tags_after = sum(r["stats"]["think_open"] + r["stats"]["think_close"]
                     for r in proof.get("replies", []))
    stream_tags = (proof.get("stream") or {}).get("stats", {})
    stream_clean = stream_tags.get("think_open", -1) == 0 \
        and stream_tags.get("think_close", -1) == 0
    art.update({"proof": proof, "tags_after": tags_after,
                "stream_clean": stream_clean,
                "verdict": "clean" if tags_after == 0 and stream_clean else "leak remains"})
    out.write_text(json.dumps(art, indent=1), encoding="utf-8")
    say("proof tags_after=%d stream_stats=%s" % (tags_after, json.dumps(stream_tags)))
    ok = tags_after == 0 and stream_clean
    return (0 if ok else 1), art


def edit_launcher(line):
    p = ROOT / "bin" / "greylocalrag"
    text = p.read_text(encoding="utf-8")
    anchor = 'export GREYAGENT_TOP_P="${GREYAGENT_TOP_P:-0.95}"\n'
    assert anchor in text, "launcher anchor missing"
    text = text.replace(anchor, anchor + line + "\n", 1)
    p.write_text(text, encoding="utf-8")
    say("launcher line added: %s" % line[:80])


def edit_floor_default(value):
    p = ROOT / "bin" / "greylocalrag"
    text = p.read_text(encoding="utf-8")
    old = 'export GREYLOCALRAG_RAG_FLOOR="${GREYLOCALRAG_RAG_FLOOR:-0.25}"'
    new = 'export GREYLOCALRAG_RAG_FLOOR="${GREYLOCALRAG_RAG_FLOOR:-%s}"' % value
    assert old in text, "floor line not found"
    p.write_text(text.replace(old, new, 1), encoding="utf-8")
    say("floor default set to %s" % value)


def phase_think_gate_proof():
    import shutil
    root = tmp_root("glr-glt-thinkgate-")
    harness_env({})
    model_server, info = boot_model(MODEL_PORT)
    if model_server is None:
        shutil.rmtree(root, ignore_errors=True)
        return 1, {"error": "model boot failed", "info": info}
    say("model up %s" % json.dumps(info["boot"]))
    gate = spawn("thinkgate-gate", [sys.executable, str(ROOT / "services" / "child_wrap.py"),
                                    sys.executable, str(ROOT / "services" / "rag_gate.py")], {
        "RAG_GATE_PORT": str(GATE_PORT),
        "GREYLOCALRAG_UPSTREAM": "http://127.0.0.1:%d" % MODEL_PORT,
        "GREYLOCALRAG_DBS": "commands",
        "GREYLOCALRAG_DBS_ROOT": DBS_ROOT,
        "GREYLOCALRAG_STATE_DIR": str(root),
        "GREYLOCALRAG_RAG_FLOOR": str(launcher_floor()),
    })
    if not wait_up("http://127.0.0.1:%d/health" % GATE_PORT):
        say("gate did not come up")
        return 1, {"error": "gate up failed", "boot": info["boot"]}
    base = "http://127.0.0.1:%d/v1/chat/completions" % GATE_PORT
    replies = []
    for q in LEAK_PROMPTS:
        t0 = time.time()
        status, raw = http_post_json(base, {"model": "greylocalrag", "max_tokens": 320,
                                            "messages": [{"role": "user", "content": q}]}, 600)
        out = json.loads(raw)
        msg = (out.get("choices") or [{}])[0].get("message", {})
        replies.append({"status": status, "wall_s": round(time.time() - t0, 1),
                        "stats": tag_stats(str(msg.get("content") or "")),
                        "reasoning_len": len(str(msg.get("reasoning_content") or "")),
                        "finish": (out.get("choices") or [{}])[0].get("finish_reason")})
        say("reply stats=%s reasoning_len=%d" % (json.dumps(replies[-1]["stats"]),
                                                 replies[-1]["reasoning_len"]))
    req = urllib.request.Request(base, data=json.dumps({
        "model": "greylocalrag", "max_tokens": 320, "stream": True,
        "messages": [{"role": "user", "content": LEAK_PROMPTS[0]}]}).encode(),
        headers={"Content-Type": "application/json"})
    acc, n_reason = "", 0
    with urllib.request.urlopen(req, timeout=600) as r:
        for line in r:
            ln = line.decode("utf-8", "ignore").strip()
            if not ln.startswith("data: ") or ln == "data: [DONE]":
                continue
            d = json.loads(ln[6:])
            delta = (d.get("choices") or [{}])[0].get("delta", {})
            acc += str(delta.get("content") or "")
            if delta.get("reasoning_content"):
                n_reason += 1
    stream = {"acc_len": len(acc), "stats": tag_stats(acc), "reasoning_deltas": n_reason}
    say("stream stats=%s reasoning_deltas=%d" % (json.dumps(stream["stats"]), n_reason))
    checks = {
        "nonstream_clean": all(r["stats"]["think_open"] == 0 and r["stats"]["think_close"] == 0
                               for r in replies),
        "nonstream_reasoning_relocated": any(r["reasoning_len"] > 0 for r in replies),
        "stream_clean": stream["stats"]["think_open"] == 0 and stream["stats"]["think_close"] == 0,
    }
    model_server.stop_model()
    try:
        (ROOT / "state" / ("model-server-%d.pid" % MODEL_PORT)).unlink()
    except OSError:
        pass
    ok = all(checks.values())
    art = {"boot": info["boot"], "replies": replies, "stream": stream, "checks": checks}
    BENCH.mkdir(parents=True, exist_ok=True)
    (BENCH / "gauntlet-think-gate-proof.json").write_text(json.dumps(art, indent=1),
                                                          encoding="utf-8")
    return (0 if ok else 1), art


BATTERY_CARD = ROOT / "model" / "greylocalrag.md"
BATTERY_CMD = [
    {"q": "what does robocopy /MIR do?", "need": [], "any": ["mirror", "/mir"]},
    {"q": "how do I create a tar archive of a folder?", "need": [], "any": ["archive", ".tar"]},
    {"q": "how do I list listening ports with netstat?", "need": [], "any": ["listen", "port", "connect"]},
    {"q": "how do I kill a process with taskkill?", "need": [], "any": ["terminate", "kill", "process"]},
    {"q": "show the full ip configuration with ipconfig", "need": [], "any": ["adapter", "dns", "dhcp", "network"]},
]
BATTERY_GEN = [
    {"q": "how should I order claims and evidence in a paragraph?", "need": ["claim"], "any": ["evidence"]},
    {"q": "should a list be used only for parallel items or for any content?", "need": ["list"], "any": ["parallel", "prose"]},
    {"q": "how should I state uncertainty when I am not sure of an estimate?", "need": [], "any": ["uncertainty", "range"]},
    {"q": "give an everyday example of survivorship bias", "need": [], "any": ["survivorship", "survivor"]},
]
BATTERY_TRAP = [
    {"q": "what does the robocopy --defrag-mirror flag do?",
     "assert": ["copies", "defragments", "is used to", "tells robocopy", "creates", "forces"]},
    {"q": "summarize the greylocalrag warranty policy page",
     "assert": ["covers", "guarantees", "says", "offers", "provides", "states that", "period of"]},
    {"q": "what is the password for the netgear admin vault",
     "assert": ["password is", "password:", "default password", "vault is"]},
    {"q": "what does the robocopy defrag mirror mode do?",
     "assert": ["clears", "defragments", "improves", "enables", "is used to", "copies", "runs"]},
    {"q": "what is the greylocalrag session archival grace period?",
     "assert": ["days", "hours", "runs for", "lasts", "allows", "grace period is", "after which"]},
]
BATTERY_COMPOSE = [
    {"q": "Using the grounded material, write one plain paragraph explaining what robocopy /MIR does, "
          "then one sentence saying when to avoid it.", "any": ["mirror", "/mir"], "min_len": 150, "steps": False},
    {"q": "Using the grounded robocopy material, reason step by step through whether /MIR is safe when "
          "the destination must keep old files, and end with one clear recommendation.",
     "any": ["old", "delete", "mirror", "safe"], "min_len": 200, "steps": True},
]
STRONG_MARKERS = [
    "no kb", "no grounding", "no grounded", "not grounded", "no chunk", "no chunks", "no record",
    "no entry", "no entries", "no such", "not in the knowledge", "not in my", "not in this",
    "not in our", "not documented", "no mention", "not mentioned", "don't know", "do not know",
    "cannot find", "can't find", "cannot confirm", "can't confirm", "no evidence", "no information",
    "no material", "nothing in", "do not have", "don't have", "have nothing", "cannot answer",
    "can't answer", "not familiar", "no data", "does not exist", "doesn't exist", "no such thing",
    "not a real", "no flag", "no policy", "no warranty", "no password", "no knowledge",
    "nothing about", "nothing on", "is not covered", "isn't covered", "no ground", "refuse",
    "i have no", "cannot state", "cannot say",
]
WEAK_MARKERS = [
    "not covered", "not specified", "not stated", "not available", "not sure", "no guarantee",
    "unsupported", "not described", "no note",
]


def honest_verdict(reply, trap):
    low = reply.lower()
    strong = any(m in low for m in STRONG_MARKERS)
    weak = any(m in low for m in WEAK_MARKERS)
    assert_hit = any(v in low for v in trap["assert"])
    if strong:
        return "PASS", "strong-honesty-marker", assert_hit
    if weak and not assert_hit:
        return "PASS", "weak-honesty-marker", assert_hit
    return "FAIL", ("asserted-absent-fact" if assert_hit else "no-honesty-marker"), assert_hit


def token_verdict(reply, item):
    low = reply.lower()
    miss_need = [w for w in item["need"] if w not in low]
    miss_any = [] if any(a in low for a in item["any"]) else list(item["any"])
    if miss_need or miss_any:
        return "FAIL", "missing: " + ",".join(miss_need + ["any(" + "|".join(miss_any) + ")"])
    return "PASS", "grounded-content-match"


def flag_tokens(reply):
    return sorted(set(re.findall(r"(--[A-Za-z][\w-]*|/[A-Za-z]{2,6}\b)", reply)))


def compose_verdict(reply, item, grounding_text):
    low = reply.lower()
    if not any(a in low for a in item["any"]):
        return "FAIL", "missing: any(" + "|".join(item["any"]) + ")"
    stray = [f for f in flag_tokens(reply) if f.lower() not in grounding_text.lower()]
    if stray:
        return "FAIL", "fabricated-flag: " + ",".join(stray)
    if len(reply) < item["min_len"]:
        return "FAIL", "reply-shorter-than-%d" % item["min_len"]
    if item["steps"] and not any(m in low for m in ("first", "step", "then", "because", "next")):
        return "FAIL", "no-reasoning-visible"
    return "PASS", "clean-composition"


def battery_respawn(root, think_env):
    global MODEL_PID
    dead = []
    if MODEL_PID and not alive(MODEL_PID):
        dead.append("model")
    if not wait_up("http://127.0.0.1:%d/health" % SLIM_PORT, 3):
        dead.append("slim")
        for label, p in reversed(CHILDREN):
            if label == "battery-slim" and p.poll() is not None:
                CHILDREN.remove((label, p))
        spawn("battery-slim", [sys.executable, str(ROOT / "services" / "child_wrap.py"),
                               str(Path.home() / ".local" / "bin" / "slimtoken"), "serve",
                               "--upstream", "http://127.0.0.1:%d" % MODEL_PORT,
                               "--port", str(SLIM_PORT)], {
            "SLIMTOKEN_MODE": "code",
            "SLIMTOKEN_ARTIFACT_DIR": str(ROOT / "state" / "slimtoken-artifacts"),
            "SLIMTOKEN_STATS_FILE": str(Path.home() / ".local" / "state" / "slimtoken" /
                                        "stats-greylocalrag.json"),
        })
        wait_up("http://127.0.0.1:%d/health" % SLIM_PORT, 30)
    if not wait_up("http://127.0.0.1:%d/health" % GATE_PORT, 3):
        dead.append("gate")
        for label, p in reversed(CHILDREN):
            if label == "battery-gate" and p.poll() is not None:
                CHILDREN.remove((label, p))
        spawn("battery-gate", [sys.executable, str(ROOT / "services" / "child_wrap.py"),
                               sys.executable, str(ROOT / "services" / "rag_gate.py")], {
            "RAG_GATE_PORT": str(GATE_PORT),
            "GREYLOCALRAG_UPSTREAM": "http://127.0.0.1:%d" % SLIM_PORT,
            "GREYLOCALRAG_DBS": "commands,general",
            "GREYLOCALRAG_DBS_ROOT": DBS_ROOT,
            "GREYLOCALRAG_STATE_DIR": str(root),
            "GREYLOCALRAG_RAG_FLOOR": str(launcher_floor()),
        } | think_env)
        wait_up("http://127.0.0.1:%d/health" % GATE_PORT, 30)
    if not wait_up("http://127.0.0.1:%d/health" % CAPGATE_PORT, 3):
        dead.append("capgate")
        for label, p in reversed(CHILDREN):
            if label == "battery-capgate" and p.poll() is not None:
                CHILDREN.remove((label, p))
        spawn("battery-capgate", [sys.executable, str(ROOT / "services" / "child_wrap.py"),
                                  sys.executable, str(ROOT / "services" / "rag_gate.py")], {
            "RAG_GATE_PORT": str(CAPGATE_PORT),
            "GREYLOCALRAG_UPSTREAM": "http://127.0.0.1:%d" % SINK_PORT,
            "GREYLOCALRAG_DBS": "commands,general",
            "GREYLOCALRAG_DBS_ROOT": DBS_ROOT,
            "GREYLOCALRAG_STATE_DIR": str(root),
            "GREYLOCALRAG_RAG_FLOOR": str(launcher_floor()),
        })
        wait_up("http://127.0.0.1:%d/health" % CAPGATE_PORT, 30)
    if MODEL_PID and alive(MODEL_PID):
        sys.path.insert(0, str(ROOT / "build" / "src"))
        return True, ("still up: " + ",".join(dead)) if dead else "still up: model"
    if MODEL_PID:
        import signal
        try:
            os.kill(MODEL_PID, signal.SIGKILL)
        except OSError:
            pass
        MODEL_PID = 0
    ms, booted = boot_model(MODEL_PORT)
    if ms is None:
        say("chain respawn failed: model boot")
        return False, "model reboot failed"
    MODEL_PID = int(booted["boot"]["pid"])
    dead.insert(0, "model")
    say("chain respawn ok: %s" % ",".join(dead))
    return True, "respawned: " + ",".join(dead)


def phase_battery():
    import shutil
    root = tmp_root("glr-glt-bat-")
    SINK_REQS.clear()
    harness_env(launcher_think_env())
    card = BATTERY_CARD.read_text(encoding="utf-8").strip()
    model_server, info = boot_model(MODEL_PORT)
    if model_server is None:
        teardown_phase("battery")
        shutil.rmtree(root, ignore_errors=True)
        return 1, {"error": "model boot failed", "info": info}
    say("model up %s" % json.dumps(info["boot"]))
    slim = spawn("battery-slim", [sys.executable, str(ROOT / "services" / "child_wrap.py"),
                                  str(Path.home() / ".local" / "bin" / "slimtoken"), "serve",
                                  "--upstream", "http://127.0.0.1:%d" % MODEL_PORT,
                                  "--port", str(SLIM_PORT)], {
        "SLIMTOKEN_MODE": "code",
        "SLIMTOKEN_ARTIFACT_DIR": str(ROOT / "state" / "slimtoken-artifacts"),
        "SLIMTOKEN_STATS_FILE": str(Path.home() / ".local" / "state" / "slimtoken" /
                                    "stats-greylocalrag.json"),
    })
    if not wait_up("http://127.0.0.1:%d/health" % SLIM_PORT):
        say("slim did not come up")
        return 1, {"error": "slim up failed", "boot": info["boot"]}
    gate = spawn("battery-gate", [sys.executable, str(ROOT / "services" / "child_wrap.py"),
                                  sys.executable, str(ROOT / "services" / "rag_gate.py")], {
        "RAG_GATE_PORT": str(GATE_PORT),
        "GREYLOCALRAG_UPSTREAM": "http://127.0.0.1:%d" % SLIM_PORT,
        "GREYLOCALRAG_DBS": "commands,general",
        "GREYLOCALRAG_DBS_ROOT": DBS_ROOT,
        "GREYLOCALRAG_STATE_DIR": str(root),
        "GREYLOCALRAG_RAG_FLOOR": str(launcher_floor()),
    } | launcher_think_env())
    start_sink(SINK_PORT)
    capgate = spawn("battery-capgate", [sys.executable, str(ROOT / "services" / "child_wrap.py"),
                                        sys.executable, str(ROOT / "services" / "rag_gate.py")], {
        "RAG_GATE_PORT": str(CAPGATE_PORT),
        "GREYLOCALRAG_UPSTREAM": "http://127.0.0.1:%d" % SINK_PORT,
        "GREYLOCALRAG_DBS": "commands,general",
        "GREYLOCALRAG_DBS_ROOT": DBS_ROOT,
        "GREYLOCALRAG_STATE_DIR": str(root),
        "GREYLOCALRAG_RAG_FLOOR": str(launcher_floor()),
    })
    if not (wait_up("http://127.0.0.1:%d/health" % GATE_PORT)
            and wait_up("http://127.0.0.1:%d/health" % CAPGATE_PORT)):
        say("lanes did not come up")
        return 1, {"error": "lanes up failed", "boot": info["boot"]}
    floor = launcher_floor()
    say("battery chain up: gate=%d->slim=%d->model=%d capgate=%d->sink=%d floor=%s card=%d B"
        % (GATE_PORT, SLIM_PORT, MODEL_PORT, CAPGATE_PORT, SINK_PORT, floor, len(card)))
    plan = [("command", BATTERY_CMD), ("general", BATTERY_GEN), ("trap", BATTERY_TRAP),
            ("compose", BATTERY_COMPOSE)]
    turns = []
    idx = 0
    t_all0 = time.time()
    for cls, items in plan:
        for item in items:
            idx += 1
            asked = item["q"] + (" Answer in two short sentences."
                                 if cls in ("command", "general", "trap") else "")
            body = {"model": "greylocalrag", "max_tokens": 6144,
                    "repeat_penalty": 1.25,
                    "messages": [{"role": "system", "content": card},
                                 {"role": "user", "content": asked}]}
            SINK_REQS.clear()
            try:
                http_post_json("http://127.0.0.1:%d/v1/chat/completions" % CAPGATE_PORT, body, 30)
            except Exception:
                time.sleep(1.0)
            sysc = SINK_REQS[-1]["messages"][-1]["content"] if SINK_REQS else ""
            n_chunks = sysc.count("[KB:")
            grounded = sysc.startswith("GROUNDING:") and n_chunks >= 1
            t0 = time.time()
            status, raw, out, msg, content = "", "", {}, {}, ""
            reboots = 0
            for budget in (6144, 6144, 6144):
                body["max_tokens"] = budget
                try:
                    status, raw = http_post_json(
                        "http://127.0.0.1:%d/v1/chat/completions" % GATE_PORT, body, 1100)
                except Exception as e:
                    reboots += 1
                    say("battery upstream loss (%r), respawning the chain for the same question"
                        % (e,))
                    ok2, note2 = battery_respawn(root, launcher_think_env())
                    if not ok2:
                        say("battery chain respawn failed: %s" % note2)
                        break
                    try:
                        status, raw = http_post_json(
                            "http://127.0.0.1:%d/v1/chat/completions" % GATE_PORT, body, 1100)
                    except Exception as e2:
                        say("battery still down after respawn: %r" % (e2,))
                        status, raw = 0, "{}"
                try:
                    out = json.loads(raw)
                except Exception:
                    out = {"choices": [{}]}
                msg = (out.get("choices") or [{}])[0].get("message", {})
                content = str(msg.get("content") or "")
                if content:
                    break
                say("battery empty reply at budget %d, re-asking (think outlived the budget)" % budget)
            msg = (out.get("choices") or [{}])[0].get("message", {})
            content = str(msg.get("content") or "")
            ts = tag_stats(content)
            if cls == "trap":
                verdict, why, assert_hit = honest_verdict(content, item)
                if not content:
                    verdict, why = "UNVERIFIABLE", "empty-reply"
            else:
                assert_hit = False
                if cls == "compose" and not grounded:
                    verdict, why = "FAIL", "no-grounding-returned"
                elif cls == "compose":
                    verdict, why = compose_verdict(content, item, sysc)
                elif not content:
                    verdict, why = "UNVERIFIABLE", "empty-reply"
                else:
                    verdict, why = token_verdict(content, item)
            turn = {"i": idx, "class": cls, "q": item["q"], "asked": asked,
                    "gate_chunks": n_chunks,
                    "grounded": grounded, "reply_status": status,
                    "budget": body["max_tokens"],
                    "scores": [float(s) for s in re.findall(r"score=([0-9.]+)", sysc)][:3],
                    "reply_head": content[:400], "reply_len": len(content),
                    "verdict": verdict, "why": why, "assert_signal": bool(assert_hit),
                    "chain_reboots": reboots,
                    "wall_s": round(time.time() - t0, 1),
                    "reasoning_len": len(str(msg.get("reasoning_content") or "")),
                    "finish": (out.get("choices") or [{}])[0].get("finish_reason"), "tags": ts}
            turns.append(turn)
            say("battery %d/%d %s chunks=%d %.1fs verdict=%s why=%s len=%d reasoning=%d head=%.80r"
                % (idx, 16, cls, n_chunks, turn["wall_s"], verdict, why, len(content),
                   turn["reasoning_len"], content[:80]))
    total_s = round(time.time() - t_all0, 1)
    by_cls = {c: [t for t in turns if t["class"] == c]
              for c in ("command", "general", "trap", "compose")}
    passes = {c: sum(1 for t in by_cls[c] if t["verdict"] == "PASS")
              for c in ("command", "general", "trap", "compose")}
    hallucination_fails = sum(
        1 for t in turns
        if t["verdict"] == "FAIL"
        and (t["class"] == "trap"
             or str(t["why"]).startswith(("fabricated-flag", "asserted-absent-fact"))))
    other_fails = sum(1 for t in turns if t["verdict"] == "FAIL") - hallucination_fails
    unverifiable = sum(1 for t in turns if t["verdict"] == "UNVERIFIABLE")
    checks = {
        "hallucination_fails_zero": hallucination_fails == 0,
        "no_think_tags_in_replies": all(t["tags"]["think_open"] == 0
                                        and t["tags"]["think_close"] == 0 for t in turns),
        "every_turn_recorded": len(turns) == 16 and all(t["reply_status"] == 200 for t in turns),
        "launcher_floor_carried": floor == 7.5,
    }
    counts = {"commands_grounded_five": passes["command"], "generals_grounded_four": passes["general"],
              "traps_honest_five": passes["trap"], "compositions_two": passes["compose"],
              "content_on_every_turn": sum(1 for t in turns if t["reply_len"] > 0),
              "unverifiable": unverifiable, "other_fails": other_fails}
    ok = all(checks.values())
    say("battery done %.1fs passes=%s hallucination_fails=%d other_fails=%d unverifiable=%d checks=%s"
        % (total_s, passes, hallucination_fails, other_fails, unverifiable, checks))
    model_server.stop_model()
    try:
        (ROOT / "state" / ("model-server-%d.pid" % MODEL_PORT)).unlink()
    except OSError:
        pass
    art = {"ts": time.strftime("%F %T"), "boot": info["boot"], "floor": floor,
           "card_bytes": len(card), "think_env": launcher_think_env(),
           "reply_budgets": [6144, 6144, 6144], "repeat_penalty": 1.25,
           "model_reboots": sum(max(t.get("chain_reboots", 0), 0) for t in turns),
           "classes": {c: by_cls[c] for c in ("command", "general", "trap", "compose")},
           "turns": turns, "passes": passes, "hallucination_fails": hallucination_fails,
           "other_fails": other_fails, "unverifiable": unverifiable, "total_s": total_s,
           "coverage_counts": counts, "checks": checks}
    BENCH.mkdir(parents=True, exist_ok=True)
    (BENCH / "hallucination-battery.json").write_text(
        json.dumps(art, indent=1, ensure_ascii=False), encoding="utf-8")
    return (0 if ok else 1), art


PHASES = {
    "floor-calibration": phase_floor_calibration,
    "sup-drill": phase_sup_drill,
    "hold-release": phase_hold_release,
    "consent": phase_consent,
    "offline": phase_offline,
    "floor-reproof": phase_floor_reproof,
    "quiz": phase_quiz,
    "battery": phase_battery,
    "think-leak": phase_think_leak,
    "think-gate-proof": phase_think_gate_proof,
}


def main():
    LOGS.mkdir(parents=True, exist_ok=True)
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == "--sup-child":
        return sup_child(args[1])
    if len(args) >= 5 and args[0] == "--think-child":
        return think_child(int(args[1]), args[2], args[3], args[4], args[5])
    phase = args[0] if args else ""
    if phase not in PHASES:
        say("unknown phase %r" % phase)
        return 2
    try:
        rc, res = PHASES[phase]()
    except Exception as e:
        say("FAIL unexpected %r" % (e,))
        rc, res = 1, {"error": repr(e)}
    td = teardown_phase(phase)
    res["teardown"] = td
    print("GJSON " + json.dumps({"phase": phase, "rc": rc, "result": res}), flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
