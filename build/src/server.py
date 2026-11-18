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

# 2026-10-25 (greymicroagent fork): the server is greymicroagent's OWN freshly built copy
# from /home/grey/llama.cpp (b3fa6995) — vendor/greymicroagent-server/ (binary renamed
# from greymini-server 2026-11-17 so the name is fork-unique) +
# every llama/ggml lib patched to resolve $ORIGIN, so this tree never touches
# the shared /home/grey/llama.cpp build, greyagent's vendored copy, or the
# lanes other harnesses use (:11435/:11436/:11598/:11599/:11600). Model
# port: owner 2026-11-17 gave this fork the unique block 7640-7647 (nothing
# else on the machine claims it; below the ephemeral range): the launcher
# ALLOCATES a slot and exports GREYAGENT_MODEL_PORT/GREYAGENT_LANE_PORT —
# pairs (7640,7641) through (7646,7647).
# Defaults here keep a direct, un-slotted boot working. The old build could
# not load this model (per-layer kv-head array + ollama tensor naming) — the
# fresh build matches the file's loader layout.
LLAMA_SERVER = str(ROOT / "vendor" / "greymicroagent-server" / "greymicroagent-server")
LLAMA_LIB_DIR = str(Path(LLAMA_SERVER).parent)
LANE_PORT = int(os.environ.get("GREYAGENT_LANE_PORT", "7641"))
# Owner 2026-11-16: RAG default model = huihui qwen3-vl 2B (abliterated), served
# from the fork-own gguf (weights are a symlink to the immutable ollama store
# blob). The classic 2B stays available via GREYMICROAGENT_MODEL_PATH override.
MODEL_PATH = os.environ.get(
    "GREYMICROAGENT_MODEL_PATH",
    "/home/grey/.greymicroagent/models/qwen3-vl-2b-abliterated.gguf",
)
PORT = int(os.environ.get("GREYAGENT_MODEL_PORT", "7640"))
HOST = "127.0.0.1"
# Owner 2026-10-25: "increase context window to 64k and ensure truncation
# doesn't happen." Default 65536; boot ladder steps down 16k (64k → 48k → 32k)
# when a sibling instance shares the card, floor 32768. Overflow never reaches
# a 400 in normal use: the lane distills any single tool result over
# SLIMTOKEN_DISTILL_MAX_CHARS (launcher, 24000 ≈ 6k tokens) and the TUI
# auto-compacts at reserveTokens (8192) — two independent guards.
CTX = int(os.environ.get("GREYAGENT_CTX", "65536"))  # FIXED window, one configuration (owner law: CPU/RAM only, no ladder, no tiers).  # greymicroagent: 64k — the 2B hybrid's KV is tiny
FA = os.environ.get("GREYAGENT_FA", "on")  # owner 2026-10-24: fill the 16GB card (hybrid model: KV is cheap); ladder steps down 16k until one fits
# 2026-10-25 (owner: greymicroagent runs CPU-only): the 27B sibling holds the 16 GB
# card, so this 2B cannot offload. NGL=0 = CPU+RAM mode — 11.7 tok/s decode
# measured on this i7-12800H, the accepted price for running beside the 27B.
# 2026-11-18 (owner: target devices = Lenovo Helix 2 + Surface, iGPU only,
# LOW SYSTEM RESOURCE): the product is CPU+RAM by construction. The GPU
# ladder is gone; GREYAGENT_NGL env can still force offload for tests.
NGL = int(os.environ.get("GREYAGENT_NGL", "0") or 0)  # CPU/RAM ONLY (owner law): baked 0; env override for tests, nothing automatic.
# 2026-10-25 (owner: "it's not giving any messages"): Qwen3.5 thinks by default.
# On CPU at ~11 tok/s the reasoning stream ate the whole reply budget and the
# OpenAI response came back with EMPTY content (finish_reason "length"), which
# the TUI renders as no message at all. Thinking off is the correct default for
# this 2B; GREYAGENT_THINKING=on restores it.
def physical_cores_default() -> int:
    # Owner 2026-11-18: "increase to the device limit but don't set a specific
    # number, it may change per device." Count PHYSICAL cores (hyperthread
    # siblings decode worse than they count, 2026-11-18 sweep: 8=25.8 tok/s,
    # 14=28.3), fall back to the OS-granted CPU count, never exceed it.
    try:
        cores = set()
        pkg = None
        cid = None
        for line in open("/proc/cpuinfo"):
            if line.startswith("physical id"):
                pkg = int(line.split(":")[1])
            elif line.startswith("core id"):
                cid = int(line.split(":")[1])
                if pkg is not None:
                    cores.add((pkg, cid))
                    pkg = cid = None
        n = len(cores)
    except Exception:
        n = 0
    try:
        logical = len(os.sched_getaffinity(0))
    except Exception:
        logical = os.cpu_count() or 4
    if not (1 <= n <= logical):
        n = max(1, logical)
    return max(1, min(n, logical))


THREADS = int(os.environ.get("GREYMICROAGENT_THREADS", "") or physical_cores_default())
THINKING = os.environ.get("GREYAGENT_THINKING", "off").strip().lower()
# GM-23 (2026-11-03): ONE sampling place — these server defaults only fire for
# requests that carry no sampling params (lane probes, doctor). The TUI's
# models.ts always sends GREYAGENT_TEMP/GREYAGENT_TOP_P (0.1/0.95 from the
# launcher; owner 2026-11-16 set the 0.0-0.2 RAG band — ollama's own params
# blob wanted temp 1, this fork deliberately runs cold); the old 0.6 here meant
# a param-less caller sampled differently from every TUI turn. Aligned.
TEMP = 0.1
TOP_P = 0.95
TOP_K = 10
# 2026-10-28 (owner: "implement ngram-mod"): n-gram speculative decoding.
# No draft model is loaded — the vendored llama.cpp (b3fa6995) keeps a fixed
# hash table of observed n-grams (~16 MB, constant cost) and drafts the token
# that followed the same n-gram before. It only drafts when a long match
# exists, so short tool-call/classification answers pay nothing while long
# copy/rewrite/summary output (the case it is documented for, and the one
# measured fastest on CPU) gets drafted ahead. GREYMICROAGENT_SPEC=off disables it
# and restores the previous boot line; GREYMICROAGENT_SPEC=<type> selects another
# --spec-type (draft-dflash etc. still need their own draft model).
SPEC = os.environ.get("GREYMICROAGENT_SPEC", "ngram-mod").strip().lower()
SPEC_ARGS = ([] if SPEC in ("", "off", "none", "0") else ["--spec-type", SPEC])
# 2026-11-18 runaway guard: ngram spec drafting accelerates self-repeats,
# so loops starve by penalty (env-off with GREYMICROAGENT_REPEAT_PENALTY=off).
_RP = os.environ.get("GREYMICROAGENT_REPEAT_PENALTY", "1.05").strip().lower()
_RPN = os.environ.get("GREYMICROAGENT_REPEAT_LAST_N", "256")
if SPEC == "ngram-mod":
    SPEC_ARGS += ["--spec-ngram-mod-n-match", os.environ.get("GREYMICROAGENT_SPEC_NMATCH", "24"),
                  "--spec-ngram-mod-n-min", os.environ.get("GREYMICROAGENT_SPEC_NMIN", "48"),
                  "--spec-ngram-mod-n-max", os.environ.get("GREYMICROAGENT_SPEC_NMAX", "64")]

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
    """Boot once with the fixed configuration. No ladder, no tiers, no
    stepping down: a failed boot is a hard error naming what broke
    (owner 2026-11-18: 'stop making tiers')."""
    global _proc
    if is_ready():
        return {"ok": True, "already": True}
    result = _boot_server(CTX, timeout)
    if result.get("ok"):
        return result
    return result


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
                "--threads", str(THREADS),
        "--flash-attn", FA,
        "--parallel", os.environ.get("GREYAGENT_PARALLEL", "1"),
        # 2026-11-18 (owner: minutes of silent prefill): the masked family knob
# left this at 128, so every TUI prompt prefilled ~50 sequential CPU
# micro-batches. 4096 is the CPU-safe batch; GREYAGENT_UBATCH still wins.
        "--ubatch-size", os.environ.get("GREYAGENT_UBATCH", "4096"),
        "--cache-type-k", os.environ.get("GREYAGENT_CTYPE", "q4_0"),
        "--cache-type-v", os.environ.get("GREYAGENT_CTYPE", "q4_0"),
        "--metrics",
        "--jinja",
        *([] if THINKING == "on" else ["--reasoning", "off"]),
        *SPEC_ARGS,
        *([] if _RP in ("", "off", "none", "0") else ["--repeat-penalty", _RP]),
        *([] if _RP in ("", "off", "none", "0") else ["--repeat-last-n", _RPN]),
        "--alias", "greymicroagent",
    ]
    log = open(STATE / "model-server.log", "ab")
    log.write(("\n=== boot attempt ctx=%d ===\n" % ctx_size).encode())
    log.flush()
    env = dict(os.environ)
    env["LD_LIBRARY_PATH"] = LLAMA_LIB_DIR  # resolve vendored libs from $ORIGIN
    # CPU-only mode must HIDE the device, not just pass --n-gpu-layers 0:
    # common_params_fit_impl probes CUDA during startup and aborts with a
    # "CUDA error: ... synchronize" core dump when the 27B already holds the
    # card (reproduced 2026-10-25). With no visible device the probe is skipped
    # and the model loads cleanly into RAM.
    if NGL == 0:
        env["CUDA_VISIBLE_DEVICES"] = ""

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
    try:
        (STATE / f"model-server-{PORT}.pid").write_text(str(_proc.pid))  # per-slot: sibling sessions never reap each other
    except Exception:
        pass
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
