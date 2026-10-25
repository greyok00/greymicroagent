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

# 2026-10-25 (greymini fork): the server is greymini's OWN freshly built copy
# from /home/grey/llama.cpp (b3fa6995) — vendor/greymini-server/, binary +
# every llama/ggml lib patched to resolve $ORIGIN, so this tree never touches
# the shared /home/grey/llama.cpp build, greyagent's vendored copy, or the
# lanes other harnesses use (:11435/:11436/:11598/:11599/:11600). Model
# port: phase 1 kept :7080/:7081. Owner 2026-10-25 ("don't ruin the current
# running one; a new launch uses new ports"): the launcher ALLOCATES a slot and
# exports GREYAGENT_MODEL_PORT/GREYAGENT_LANE_PORT — slot 1 stays 7080/7081
# (the original instance keeps it), new sessions take 4444-4447 / 4454-4457.
# Defaults here keep a direct, un-slotted boot working. The old build could
# not load this model (per-layer kv-head array + ollama tensor naming) — the
# fresh build matches the file's loader layout.
LLAMA_SERVER = str(ROOT / "vendor" / "greymini-server" / "greymini-server")
LLAMA_LIB_DIR = str(Path(LLAMA_SERVER).parent)
LANE_PORT = int(os.environ.get("GREYAGENT_LANE_PORT", "7081"))
MODEL_PATH = "/home/grey/.greymini/models/qwen3.5-2b-abliterated.gguf"
PORT = int(os.environ.get("GREYAGENT_MODEL_PORT", "7080"))
HOST = "127.0.0.1"
# Owner 2026-10-25: "increase context window to 64k and ensure truncation
# doesn't happen." Default 65536; boot ladder steps down 16k (64k → 48k → 32k)
# when a sibling instance shares the card, floor 32768. Overflow never reaches
# a 400 in normal use: the lane distills any single tool result over
# SLIMTOKEN_DISTILL_MAX_CHARS (launcher, 24000 ≈ 6k tokens) and the TUI
# auto-compacts at reserveTokens (8192) — two independent guards.
CTX = int(os.environ.get("GREYAGENT_CTX", "65536"))  # greymini: 64k — the 2B hybrid's KV is tiny
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


def start_model(timeout: float = 300.0) -> dict:
    global _proc
    if is_ready():
        return {"ok": True, "already": True}
    # NO auto-kill in greymini (owner 2026-10-25: sibling instances must never
    # be killed by a sibling's boot; the launcher's VRAM gate REFUSES foreign
    # holders instead — refuse-only policy).
    # Fill-the-card ladder (owner 2026-10-24: "increase to 16gb ... greyagent
    # takes vram precedence"): boot the largest window the card can hold.
    # Each OOM costs one boot cycle only; the first size that stays up
    # settles and is reused on the next boot. With the card to itself this
    # lands near ~100k tokens; smaller steps exist for when VRAM is shared.
    ctx_note = STATE / "model-ctx-settled.txt"
    candidates = sorted(set(list(range(CTX, 24576, -16384)) + [32768]), reverse=True)
    # greymini: 32k floor — the ladder stops AT 32768, never lower
    # (owner 2026-10-25: 64k default; a shrunken window would re-introduce
    # the overflow class, so the ladder never goes below half)
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
    (STATE / f"model-server-{PORT}.pid").write_text(str(_proc.pid))  # per-slot: sibling sessions never reap each other
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
    (STATE / f"model-server-{PORT}.pid").unlink(missing_ok=True)


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
