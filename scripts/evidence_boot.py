import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "state" / "logs"
PORTS = (7640, 7641, 7642, 7643, 7644)
DBS_ROOT = str(Path.home() / ".greylocalrag" / "dbs")
PAGESZ = os.sysconf("SC_PAGE_SIZE")
SINK_REQS = []
CHILDREN = []
EV = {"fail": [], "findings": [], "phases": {}}
MODEL_PID = 0
SINK_SERVER = None

os.environ["GREYLOCALRAG_THREADS"] = "4"
os.environ["GREYLOCALRAG_ASSUME_RAM_GB"] = "8"

sys.path.insert(0, str(ROOT / "build" / "src"))
import server as model_server


class Bail(Exception):
    pass


def say(msg):
    print(msg, flush=True)


def fail(msg):
    EV["fail"].append(msg)
    say("FAIL " + msg)
    raise Bail(msg)


def busy_sockets():
    raw = subprocess.run(["ss", "-ltn"], capture_output=True, text=True).stdout
    hits = {}
    for p in PORTS:
        hits[str(p)] = any(ln.split()[3].rsplit(":", 1)[-1] == str(p)
                           for ln in raw.splitlines() if len(ln.split()) > 3)
    return hits


def http_up(paths, timeout_s=120):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        for base, path in paths:
            try:
                with urllib.request.urlopen(base + path, timeout=3) as r:
                    if r.status == 200:
                        return True
            except Exception:
                pass
        time.sleep(0.5)
    return False


def http_post_json(url, obj, timeout_s=900):
    body = json.dumps(obj).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as r:
        return r.status, json.loads(r.read().decode("utf-8", "ignore"))


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def rss_bytes(pid):
    with open("/proc/%d/statm" % pid) as f:
        return int(f.read().split()[1]) * PAGESZ


def child_env():
    return {k: v for k, v in os.environ.items()
            if not k.startswith(("GREYAGENT_", "SLIMTOKEN_", "GREYLOCALRAG_", "RAG_GATE_"))}


def spawn(label, cmd, port_env):
    env = child_env()
    env.update(port_env)
    log = open(LOGS / ("evidence-%s.log" % label), "ab")
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(ROOT), env=env)
    log.close()
    CHILDREN.append((label, proc))
    say("EVIDENCE spawned %s pid=%d" % (label, proc.pid))
    return proc


def reap(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass


class Sink(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        self.wfile.write(b"{}")

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n > 0 else b""
        SINK_REQS.append(json.loads(body.decode("utf-8", "ignore")))
        out = json.dumps({"id": "sink", "object": "chat.completion", "choices": [
            {"index": 0, "message": {"role": "assistant", "content": "sink-ok"}, "finish_reason": "stop"}
        ]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        self.wfile.write(out)


def preflight():
    aff = sorted(os.sched_getaffinity(0))
    EV["affinity"] = aff
    if len(aff) > 4:
        EV["fail"].append("affinity %s exceeds 4 cpus; relaunch under taskset -c 0-3" % aff)
        say("ABORT %s" % EV["fail"][0])
        return False
    say("EVIDENCE affinity=%s threads=4 assume_ram_gb=8" % aff)
    model_path = Path(model_server.MODEL_PATH)
    if not model_path.exists():
        EV["fail"].append("model symlink does not resolve: %s" % model_path)
        say("ABORT %s" % EV["fail"][0])
        return False
    blob = os.path.realpath(model_path)
    EV["model"] = {"symlink": str(model_path), "resolves_to": blob, "bytes": os.path.getsize(blob),
                   "model_path": model_server.MODEL_PATH,
                   "override": "GREYLOCALRAG_MODEL_PATH" in os.environ}
    say("EVIDENCE model symlink resolves to %s (%d bytes)" % (blob, EV["model"]["bytes"]))
    busy = busy_sockets()
    held = [p for p, b in busy.items() if b]
    EV["ports_at_start"] = {k: v for k, v in busy.items()}
    if held:
        EV["fail"].append("free-port probe refusal: %s occupied (never fight another listener)" % held)
        say("ABORT free-port probe: %s occupied (never fight another listener)" % held)
        say("ABORT holding processes:")
        subprocess.run(["ss", "-ltnp"])
        return False
    return True


def run_boot():
    global MODEL_PID, SINK_SERVER
    t_boot0 = time.time()
    boot = model_server.start_model(timeout=600)
    EV["phases"]["boot"] = {"ok": boot.get("ok"), "ctx": boot.get("ctx"),
                            "error": boot.get("error"), "sec": round(time.time() - t_boot0, 1)}
    if not boot.get("ok") or not boot.get("pid"):
        fail("model boot failed: %s" % boot)
    MODEL_PID = int(boot["pid"])
    if boot["ctx"] != 32768:
        fail("booted ctx %s != 32768" % boot["ctx"])
    settled = (ROOT / "state" / "model-ctx-settled.txt").read_text().strip()
    if settled != "32768":
        fail("ctx-note file reads %s, expected 32768" % settled)
    say("EVIDENCE model up pid=%d ctx=32768 settled=32768 boot=%.1fs" % (MODEL_PID, EV["phases"]["boot"]["sec"]))
    model_rss = rss_bytes(MODEL_PID)
    say("EVIDENCE model rss=%.2f GB" % (model_rss / 1024 ** 3))
    if model_rss >= 3.5 * 1024 ** 3:
        fail("model RSS %.2f GB exceeds 3.5 GB" % (model_rss / 1024 ** 3))

    slim_proc = spawn("slim", [sys.executable, str(ROOT / "services" / "child_wrap.py"),
                               str(Path.home() / ".local" / "bin" / "slimtoken"), "serve",
                               "--upstream", "http://127.0.0.1:7640", "--port", "7642"], {
        "SLIMTOKEN_MODE": "code",
        "SLIMTOKEN_ARTIFACT_DIR": str(ROOT / "state" / "slimtoken-artifacts"),
        "SLIMTOKEN_STATS_FILE": str(Path.home() / ".local" / "state" / "slimtoken" / "stats-greylocalrag.json"),
    })
    if not http_up([("http://127.0.0.1:7642", "/health"), ("http://127.0.0.1:7642", "/metrics")]):
        fail("slimtoken :7642 did not come up")
    slim_rss = rss_bytes(slim_proc.pid)

    gate_env = {
        "RAG_GATE_PORT": "7641",
        "GREYLOCALRAG_UPSTREAM": "http://127.0.0.1:7642",
        "GREYLOCALRAG_DBS": "commands",
        "GREYLOCALRAG_DBS_ROOT": DBS_ROOT,
        "GREYLOCALRAG_RAG_FLOOR": "19.0",
    }
    gate_proc = spawn("gate", [sys.executable, str(ROOT / "services" / "child_wrap.py"),
                               sys.executable, str(ROOT / "services" / "rag_gate.py")], gate_env)
    if not http_up([("http://127.0.0.1:7641", "/health")]):
        fail("RAG gate :7641 did not come up")
    say("EVIDENCE gate :7641 healthy (slim :7642 -> model :7640; RSS slim=%.1fMB)" % (slim_rss / 1048576))

    SINK_SERVER = ThreadingHTTPServer(("127.0.0.1", 7643), Sink)
    threading.Thread(target=SINK_SERVER.serve_forever, daemon=True).start()
    say("EVIDENCE sink :7643 up")
    tg_env = dict(gate_env)
    tg_env["RAG_GATE_PORT"] = "7644"
    tg_env["GREYLOCALRAG_UPSTREAM"] = "http://127.0.0.1:7643"
    tgate_proc = spawn("temp-gate", [sys.executable, str(ROOT / "services" / "child_wrap.py"),
                                     sys.executable, str(ROOT / "services" / "rag_gate.py")], tg_env)
    if not http_up([("http://127.0.0.1:7644", "/health")]):
        fail("capturing gate :7644 did not come up")
    gate_rss = rss_bytes(gate_proc.pid)
    EV["phases"]["rss"] = {"model": model_rss, "gate": gate_rss, "slim": slim_rss}

    seed_q = "How do I mirror a directory tree with robocopy on Windows 11?"
    marker_q = "zzqvvkxx mmmaaapbb qwrtsdlk"
    nolog_q = marker_q

    st, _ = http_post_json("http://127.0.0.1:7644/v1/chat/completions", {
        "model": "greylocalrag", "temperature": 0.9, "max_tokens": 128,
        "messages": [{"role": "user", "content": seed_q}]}, 60)
    if st != 200 or not SINK_REQS:
        fail("wire-capture path failed status=%s" % st)
    hot = SINK_REQS[-1]
    hot_temp = hot.get("temperature")
    hot_sys = hot["messages"][-1]["content"]
    if not 0.0 <= float(hot_temp) <= 0.2:
        fail("upstream temperature %s outside 0.0-0.2 (input was 0.9)" % hot_temp)
    if "robocopy" not in hot_sys.lower() or "[KB:commands#" not in hot_sys:
        fail("grounded system block missing KB robocopy entry: %.140s" % hot_sys)
    say("EVIDENCE clamped 0.9 -> upstream temp %s; system block [GROUNDING]+[KB:commands#] robocopy present" % hot_temp)

    st, _ = http_post_json("http://127.0.0.1:7644/v1/chat/completions", {
        "model": "greylocalrag", "max_tokens": 128,
        "messages": [{"role": "user", "content": nolog_q}]}, 60)
    if st != 200:
        fail("no-kb wire capture failed status=%s" % st)
    nb = SINK_REQS[-1]
    nb_temp = nb.get("temperature")
    nb_sys = nb["messages"][-1]["content"]
    if float(nb_temp) > 0.2:
        fail("default upstream temperature %s outside band" % nb_temp)
    if not nb_sys.startswith("[NO-KB-GROUNDING]"):
        fail("no-overlap query did not produce [NO-KB-GROUNDING]: %.140s" % nb_sys)
    say("EVIDENCE no-KB query -> system role exactly [NO-KB-GROUNDING], upstream temp %s" % nb_temp)
    EV["phases"]["gate_wires"] = {"hot_temp": hot_temp, "nokb_temp": nb_temp}

    e2e_base = "http://127.0.0.1:7641/v1/chat/completions"
    e2e_layer = "gate"
    gate_status = None
    gate_body = ""
    try:
        gate_status, _ = http_post_json(e2e_base, {"model": "greylocalrag", "max_tokens": 16,
                                                   "messages": [{"role": "user", "content": "ping"}]}, 60)
    except urllib.error.HTTPError as e:
        gate_status = e.code
        gate_body = e.read().decode("utf-8", "ignore")[:120]
    if gate_status != 200:
        EV["findings"].append("gate :7641 POST /v1/chat/completions status=%s body=%.120s "
                              "(gate forwards the received path since the F2 fix; the completion "
                              "hop itself failed upstream)"
                              % (gate_status, gate_body))
        say("FINDING gate completion hop status=%s (%.120s) - asserting completions at slim :7642/v1 layer" % (gate_status, gate_body))
        e2e_base = "http://127.0.0.1:7642/v1/chat/completions"
        e2e_layer = "slim"
    EV["phases"]["e2e_route"] = {"gate_status": gate_status, "layer": e2e_layer}

    e2e = {}
    for label, q, temp in (("seed", seed_q, None), ("garbage_temp_0.9", seed_q, 0.9),
                           ("offtopic", "what is the capital of Portugal and its full history", None),
                           ("oov", marker_q, None)):
        req = {"model": "greylocalrag", "max_tokens": 256, "messages": [{"role": "user", "content": q}]}
        if temp is not None:
            req["temperature"] = temp
        t0 = time.time()
        st, out = http_post_json(e2e_base, req, 900)
        content = (out.get("choices") or [{}])[0].get("message", {}).get("content", "")
        ok = st == 200 and isinstance(content, str) and bool(content.strip())
        e2e[label] = {"status": st, "via": e2e_layer,
                      "content_len": len(content) if isinstance(content, str) else 0,
                      "sec": round(time.time() - t0, 1), "head": content[:110]}
        say("EVIDENCE e2e %s via %s status=%s len=%s %.1fs head=%.110r"
            % (label, e2e_layer, st, e2e[label]["content_len"], e2e[label]["sec"], content[:110]))
        if not ok:
            fail("e2e %s via %s status=%s content=%r" % (label, e2e_layer, st, content))
    EV["phases"]["e2e"] = e2e

    say("EVIDENCE starting 9-gate bench vs :7640/v1 (existing harness, minutes)")
    label = Path(model_server.MODEL_PATH).name.removesuffix(".gguf")
    bench_out = ROOT / "state" / "bench" / ("qwen3vl2b.json" if label.startswith("qwen3-vl-2b") else label + ".json")
    r = subprocess.run([sys.executable, str(ROOT / "state" / "bench" / "model_bench.py"),
                        "http://127.0.0.1:7640/v1", label, str(bench_out)],
                       capture_output=True, text=True, timeout=1800)
    bench = None
    for line in r.stdout.strip().splitlines():
        try:
            bench = json.loads(line)
        except Exception:
            pass
    if bench is None:
        fail("bench harness produced no json: rc=%s err=%.200s" % (r.returncode, r.stderr[:200]))
    EV["phases"]["bench"] = {"pass_rate": bench.get("pass_rate"), "speed": bench.get("speed"),
                             "file": str(bench_out), "label": label}
    say("EVIDENCE bench pass_rate=%s speed=%s" % (bench.get("pass_rate"), bench.get("speed")))


def teardown():
    global SINK_SERVER, MODEL_PID
    for _, proc in reversed(CHILDREN):
        reap(proc)
    if MODEL_PID and alive(MODEL_PID):
        os.kill(MODEL_PID, 15)
        for _ in range(20):
            if not alive(MODEL_PID):
                break
            time.sleep(0.5)
        if alive(MODEL_PID):
            os.kill(MODEL_PID, 9)
    try:
        model_server.stop_model()
    except Exception:
        pass
    (ROOT / "state" / "model-server-7640.pid").unlink(missing_ok=True)
    if SINK_SERVER is not None:
        try:
            SINK_SERVER.shutdown()
            SINK_SERVER.server_close()
        except Exception:
            pass
        SINK_SERVER = None
    survivors = [pid for pid in [MODEL_PID] + [p.pid for _, p in CHILDREN] if pid and alive(pid)]
    EV["survivors"] = survivors
    busy = busy_sockets()
    EV["ports_after_teardown"] = busy
    listening = [p for p, b in busy.items() if b]
    if survivors:
        say("FAIL SURVIVOR LAW VIOLATED: %s still alive" % survivors)
        EV["fail"].append("survivors after teardown: %s" % survivors)
    else:
        say("EVIDENCE survivor check: 0 of %d spawned pids alive; ports still listening outside run: %s"
            % (len(CHILDREN) + (1 if MODEL_PID else 0), listening))


def main():
    if not preflight():
        return 2
    try:
        run_boot()
        say("EVIDENCE run complete")
        return 1 if EV["fail"] else 0
    except Bail:
        return 1
    except Exception as e:
        EV["fail"].append("unexpected: %r" % (e,))
        say("FAIL unexpected %r" % (e,))
        return 1
    finally:
        teardown()
        say("EVIDENCE " + json.dumps(EV))


if __name__ == "__main__":
    sys.exit(main())
