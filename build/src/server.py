from __future__ import annotations

import os
import re
import subprocess
import time
import urllib.request
from pathlib import Path

# greyagent root = two levels ABOVE this file's parent (build/src/server.py
# resolves: [repo]/build/src/server.py -> parents[2] = [repo]). 2026-10-24:
# the previous parent.parent root resolved into build/ and mispathed both the
# vendored binary and the pid/log state — the launcher reaps greyagent/state.
ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "state"
STATE.mkdir(exist_ok=True)

# 2026-10-24 (owner order: fully self-contained, masked, ports >=7080):
# greyagent serves its OWN renamed llama-server copy from vendor/ — the binary
# and every llama/ggml lib it needs are patched to resolve $ORIGIN, so this
# tree never touches the shared /home/grey/llama.cpp build or the lanes other
# harnesses use (:11435/:11436/:11598/:11599/:11600). Model port: :7080.
LLAMA_SERVER = str(ROOT / "vendor" / "llamacpp" / "greyagent-server")
LLAMA_LIB_DIR = str(Path(LLAMA_SERVER).parent)
LANE_PORT = 7081  # slimtoken lane in front of :7080 (brain traffic only)
MODEL_PATH = "/home/grey/.greymini/models/qwen3.5-2b-abliterated.gguf"
PORT = 7080
HOST = "127.0.0.1"
CTX = int(os.environ.get("GREYAGENT_CTX", "32768"))  # greymini: 32k — the 2B hybrid's KV is tiny, one rung is enough
FA = os.environ.get("GREYAGENT_FA", "on")  # owner 2026-10-24: fill the 16GB card (hybrid model: KV is cheap); ladder steps down 16k until one fits
NGL = -1
TEMP = 0.2
TOP_P = 0.9
TOP_K = 10

_proc = None


def server_url() -> str:
    return "http://%s:%d" % (HOST, PORT)


def is_ready() -> bool:
    try:
        with urllib.request.urlopen(server_url() + "/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def kill_vram_holders() -> list:
    """Kill every compute process holding VRAM that greyagent doesn't own —
    owner 2026-10-24: "greyagent takes vram precedence ... if it does [have
    company], this should kill it automatically." Whitelist: display servers
    and our own process tree (killing Xorg/Wayland would take the desktop
    down; those hold little VRAM anyway). Returns what was killed."""
    import subprocess as _sp
    killed = []
    try:
        out = _sp.run(["nvidia-smi", "--query-compute-apps=pid,process_name", "--format=csv,noheader,nounits"],
                      capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return killed
    own = set()
    p, cur = {}, os.getpid()
    while cur > 1:
        own.add(cur)
        try:
            cur = int(open(f"/proc/{cur}/stat").read().split(")")[-1].split()[1])
        except Exception:
            break
    for line in out.strip().splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) != 2 or not parts[0].isdigit():
            continue
        pid, name = int(parts[0]), parts[1]
        if pid in own:
            continue
        try:
            cmd = open(f"/proc/{pid}/cmdline", "rb").read().decode(errors="replace")
        except Exception:
            cmd = name
        if any(w in cmd for w in ("Xorg", "Xwayland", "gnome-shell", "cinnamon", "mate",
                                  "kwin", "weston", "displaylink")):
            continue  # display stack — taking the desktop down is worse than 200MB of VRAM
        try:
            os.kill(pid, _sigterm)
            time.sleep(1.0)
            try:
                os.kill(pid, 0)
                os.kill(pid, _sigkill)
            except (ProcessLookupError, PermissionError):
                pass
            killed.append(f"pid={pid} {os.path.basename(cmd.split(chr(0))[0] or name)}")
        except (ProcessLookupError, PermissionError):
            pass
    if killed:
        log = open(STATE / "model-server.log", "ab")
        log.write(("kill_vram_holders: " + ", ".join(killed) + "\n").encode())
    return killed


def start_model(timeout: float = 300.0) -> dict:
    global _proc
    if is_ready():
        return {"ok": True, "already": True}
    kill_vram_holders()
    # Fill-the-card ladder (owner 2026-10-24: "increase to 16gb ... greyagent
    # takes vram precedence"): boot the largest window the card can hold.
    # Each OOM costs one boot cycle only; the first size that stays up
    # settles and is reused on the next boot. With the card to itself this
    # lands near ~100k tokens; smaller steps exist for when VRAM is shared.
    ctx_note = STATE / "model-ctx-settled.txt"
    candidates = sorted(set(list(range(CTX, max(CTX - 1, 32767), -16384)) + [32768]), reverse=True)
    # greymini: 32k floor — the ladder stops AT 32768, never lower
    try:
        settled = int(ctx_note.read_text().strip())
        if 8192 <= settled and settled not in candidates:
            # A previously settled size is a LAST-RESORT fallback: the big
            # ladder is always tried first, so a fuller card still fills.
            if settled < candidates[-1]:
                candidates.append(settled)
    except Exception:
        pass
    last_err = None
    for ctx in candidates:
        result = _boot_server(ctx, timeout)
        if result.get("ok"):
            try:
                ctx_note.write_text(str(result.get("ctx") or ctx))
            except Exception:
                pass
            return result
        last_err = result.get("error")
        if ctx == candidates[-1]:
            break
    return {"ok": False, "error": last_err or "no ctx size held"}


def _boot_server(ctx_size: int, timeout: float) -> dict:
    global _proc
    cmd = [
        LLAMA_SERVER,
        "--model", MODEL_PATH,
        "--host", HOST,
        "--port", str(PORT),
        "--ctx-size", str(ctx_size),
        "--n-gpu-layers", str(NGL),
        "--temp", str(TEMP),
        "--top-p", str(TOP_P),
        "--top-k", str(TOP_K),
        "--threads", "8",
        "--flash-attn", FA,
        "--parallel", os.environ.get("GREYAGENT_PARALLEL", "1"),
        "--ubatch-size", os.environ.get("GREYAGENT_UBATCH", "128"),
        "--cache-type-k", os.environ.get("GREYAGENT_CTYPE", "q4_0"),
        "--cache-type-v", os.environ.get("GREYAGENT_CTYPE", "q4_0"),
        "--metrics",
        "--jinja",
        "--alias", "greymini",
    ]
    log = open(STATE / "model-server.log", "ab")
    log.write(("\n=== boot attempt ctx=%d ===\n" % ctx_size).encode())
    log.flush()
    env = dict(os.environ)
    env["LD_LIBRARY_PATH"] = LLAMA_LIB_DIR  # resolve vendored libs from $ORIGIN

    def _pdeathsig():  # noqa: E306
        # Linux PR_SET_PDEATHSIG (parent-death signal): if the loader process
        # dies for ANY reason (trap gap, hard kill, HUP), the server receives
        # SIGTERM — the orphan-server leak class is architecturally closed.
        import ctypes
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        PR_SET_PDEATHSIG = 1
        libc.prctl(PR_SET_PDEATHSIG, _sigterm, 0, 0, 0)

    import signal as _signal
    _sigterm = _signal.SIGTERM
    _proc = subprocess.Popen(cmd, stdout=log, stderr=log, close_fds=True, env=env,
                             preexec_fn=_pdeathsig)
    # pid file so the launcher can kill the server on exit even after this
    # loader process has already returned (model outlives the spawn job).
    (STATE / "model-server.pid").write_text(str(_proc.pid))
    t0 = time.time()
    while time.time() - t0 < timeout:
        if is_ready():
            return {"ok": True, "pid": _proc.pid, "ctx": ctx_size}
        if _proc.poll() is not None:
            return {"ok": False, "error": "server exited rc=%d at ctx=%d" % (_proc.returncode, ctx_size)}
        time.sleep(0.5)
    return {"ok": False, "error": "server not ready in %.0fs at ctx=%d" % (timeout, ctx_size)}


def stop_model() -> None:
    global _proc
    if _proc and _proc.poll() is None:
        _proc.terminate()
        try:
            _proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _proc.kill()
    _proc = None
    (STATE / "model-server.pid").unlink(missing_ok=True)


def tokens_per_second() -> float:
    try:
        with urllib.request.urlopen(server_url() + "/metrics", timeout=3) as r:
            text = r.read().decode()
    except Exception:
        return 0.0
    gen = re.search(r"llamacpp:tokens_predicted_total\s+([0-9.]+)", text)
    sec = re.search(r"llamacpp:tokens_predicted_seconds_total\s+([0-9.]+)", text)
    if gen and sec:
        try:
            return float(gen.group(1)) / float(sec.group(1))
        except Exception:
            return 0.0
    return 0.0
