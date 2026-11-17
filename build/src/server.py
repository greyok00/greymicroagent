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

# 2026-10-25 (greylocalrag fork): the server is greylocalrag's OWN freshly built copy
# from /home/grey/llama.cpp (b3fa6995) — vendor/greylocalrag-server/ (binary renamed
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
LLAMA_SERVER = str(ROOT / "vendor" / "greylocalrag-server" / "greylocalrag-server")
LLAMA_LIB_DIR = str(Path(LLAMA_SERVER).parent)
LANE_PORT = int(os.environ.get("GREYAGENT_LANE_PORT", "7641"))
# Owner 2026-11-16: RAG default model = huihui qwen3-vl 2B (abliterated), served
# from the fork-own gguf (weights are a symlink to the immutable ollama store
# blob). The classic 2B stays available via GREYLOCALRAG_MODEL_PATH override.
MODEL_PATH = os.environ.get(
    "GREYLOCALRAG_MODEL_PATH",
    "/home/grey/.greylocalrag/models/qwen3-vl-2b-abliterated.gguf",
)
PORT = int(os.environ.get("GREYAGENT_MODEL_PORT", "7640"))
HOST = "127.0.0.1"
# Owner 2026-10-25: "increase context window to 64k and ensure truncation
# doesn't happen." Default 65536; boot ladder steps down 16k (64k → 48k → 32k)
# when a sibling instance shares the card, floor 32768. Overflow never reaches
# a 400 in normal use: the lane distills any single tool result over
# SLIMTOKEN_DISTILL_MAX_CHARS (launcher, 24000 ≈ 6k tokens) and the TUI
# auto-compacts at reserveTokens (8192) — two independent guards.
def probe_ram_gb() -> float:
    try:
        return int(open("/proc/meminfo").readline().split()[1]) / 1048576
    except Exception:
        return 64.0


def open_ctx_default() -> int:
    assumed = os.environ.get("GREYLOCALRAG_ASSUME_RAM_GB")
    try:
        ram = float(assumed) if assumed else probe_ram_gb()
    except ValueError:
        ram = probe_ram_gb()
    return 32768 if ram <= 8 else 65536


CTX = int(os.environ.get("GREYAGENT_CTX", str(open_ctx_default())))  # greylocalrag: 64k — the 2B hybrid's KV is tiny
FA = os.environ.get("GREYAGENT_FA", "on")  # owner 2026-10-24: fill the 16GB card (hybrid model: KV is cheap); ladder steps down 16k until one fits
# 2026-10-25 (owner: greylocalrag runs CPU-only): the 27B sibling holds the 16 GB
# card, so this 2B cannot offload. NGL=0 = CPU+RAM mode — 11.7 tok/s decode
# measured on this i7-12800H, the accepted price for running beside the 27B.
NGL = int(os.environ.get("GREYAGENT_NGL", "-1"))
# 2026-10-25 (owner: "it's not giving any messages"): Qwen3.5 thinks by default.
# On CPU at ~11 tok/s the reasoning stream ate the whole reply budget and the
# OpenAI response came back with EMPTY content (finish_reason "length"), which
# the TUI renders as no message at all. Thinking off is the correct default for
# this 2B; GREYAGENT_THINKING=on restores it.
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
# measured fastest on CPU) gets drafted ahead. GREYLOCALRAG_SPEC=off disables it
# and restores the previous boot line; GREYLOCALRAG_SPEC=<type> selects another
# --spec-type (draft-dflash etc. still need their own draft model).
SPEC = os.environ.get("GREYLOCALRAG_SPEC", "ngram-mod").strip().lower()
SPEC_ARGS = ([] if SPEC in ("", "off", "none", "0") else ["--spec-type", SPEC])
if SPEC == "ngram-mod":
    SPEC_ARGS += ["--spec-ngram-mod-n-match", os.environ.get("GREYLOCALRAG_SPEC_NMATCH", "24"),
                  "--spec-ngram-mod-n-min", os.environ.get("GREYLOCALRAG_SPEC_NMIN", "48"),
                  "--spec-ngram-mod-n-max", os.environ.get("GREYLOCALRAG_SPEC_NMAX", "64")]

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
    # NO auto-kill in greylocalrag (owner 2026-10-25: sibling instances must never
    # be killed by a sibling's boot; the launcher's VRAM gate REFUSES foreign
    # holders instead — refuse-only policy).
    # Fill-the-card ladder (owner 2026-10-24: "increase to 16gb ... greyagent
    # takes vram precedence"): boot the largest window the card can hold.
    # Each OOM costs one boot cycle only; the first size that stays up
    # settles and is reused on the next boot. With the card to itself this
    # lands near ~100k tokens; smaller steps exist for when VRAM is shared.
    ctx_note = STATE / "model-ctx-settled.txt"
    base = open_ctx_default()
    candidates = sorted(set(list(range(base, 24576, -16384)) + [32768]), reverse=True)
    # greylocalrag: 32k floor — the ladder stops AT 32768, never lower
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
        "--threads", os.environ.get("GREYLOCALRAG_THREADS", "4"),
        "--flash-attn", FA,
        "--parallel", os.environ.get("GREYAGENT_PARALLEL", "1"),
        "--ubatch-size", os.environ.get("GREYAGENT_UBATCH", "128"),
        "--cache-type-k", os.environ.get("GREYAGENT_CTYPE", "q4_0"),
        "--cache-type-v", os.environ.get("GREYAGENT_CTYPE", "q4_0"),
        "--metrics",
        "--jinja",
        *([] if THINKING == "on" else ["--reasoning", "off"]),
        *SPEC_ARGS,
        "--alias", "greylocalrag",
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
