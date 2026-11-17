# greylocalrag Architecture & Model Audit

**Date:** 2026-10-27 · **Machine:** i7-12800H (20 threads), 62 GB RAM (26 GB free), RTX A4500 16 GB (held by greyagent's 27B on :7080)
**Scope:** fork harness at `~/greylocalrag` + the 2B model it runs. All numbers measured live on this machine, CPU-only, NGL=0, 8 threads, ctx 8192 (bench) / 65536 (config default).

---

## 1. What greylocalrag actually is

A **fork of the greyagent harness**, stripped to one job: run a small abliterated GGUF locally, CPU-first, with a slimtoken lane in front.

| Layer | Path | Notes |
|---|---|---|
| Launcher | `bin/greylocalrag` → `~/.local/bin/greylocalrag` | Slot allocation: model 7080 (free-fall 4444–4447), lane 7081 (4454–4457) |
| Model server | `vendor/greymini-server/greymini-server` | vendored llama.cpp build `b3fa6995` |
| Boot logic | `build/src/server.py` | ctx ladder 64k→32k floor, thinking **off** by default, `TEMP=0.2` hardcoded, q4_0 KV cache, FA on, NGL=0 CPU mode |
| Lane | slimtoken, 24 000-char distill cap | client-side in-front filter only (port policy) |
| Config | `config/settings.json` | quietStartup, compaction reserve 8192, thinking "balanced" (but server forces off) |
| Port policy | `config/port_policy.json` | 7080/7081 owned; 11600 cloud-ollama direct-only; 11434 dead; cleanup by PID only |
| Handoff job | `handoff/library-agent.py` + `AGENT-PROMPT.md` + `RUNBOOK.md` | deterministic driver; model emits ONE JSON action/turn |

**Verdict: the harness is sound.** Slot allocation, port policy, PID-only cleanup, and the ctx-descent ladder are all correct. Three small doc/config drifts (none blocking):
1. `port_policy.json` says `model_binary: vendor/llamacpp/greymini-server` — actual path is `vendor/greymini-server/`.
2. `settings.json` `defaultThinkingLevel: balanced` but `server.py` forces thinking off — harmless, but the setting is a lie.
3. Launcher exports `GREYAGENT_TEMP=0.6` while `server.py` hardcodes `TEMP=0.2` — the env var is dead.

## 2. Behavior audit (9 sessions, 2026-10-25, 580 tool calls)

| Metric | Value |
|---|---|
| Tool calls | 580 (bash 359, write 11, read 7, edit 4, clickworker-MCP ~9) |
| Tool errors | **0** |
| Valid JSON tool-call rate | 100% (json_toolcall + json_multi_field PASS in bench) |

**What it did well:** long bash chains, ClickWorker tick loop (8 clean turns + correct status report), research-library audit (found 490 violations across 135 pages), handoff-kit authoring.

**Where it broke (owner-reported):**
- **Looping** — "WHY ARE YOU LOOPING" — re-reading/re-writing the same files instead of advancing the queue.
- **NSCE.gov hallucination** — repeated the wrong name 4× after being told to remove it. A 2B's context is too small to hold a multi-turn correction + the full taxonomy.
- **Empty replies** — documented in `server.py` comments as a known 2B failure class.
- **Instruction drift** — re-wrote the handoff kit 3× instead of editing in place.

## 3. Live benchmark (this machine, CPU-only, fixed harness)

Harness: `state/bench/model_bench.py` — 9-task agent suite (tool-call JSON, multi-field JSON, instruction follow, math ×2, code exec, extraction, summarize, negation). Speed = 60-token count.

| | **2B** (current) | **4B** Q4_K_M | **35B-A3B** Opus-abl IQ3_XXS (MoE) |
|---|---|---|---|
| **Decode speed** | **7.7 t/s** | 3.1 t/s | 2.7 t/s |
| **Pass rate** | 7/9 | 7/9 | **8/9** |
| json_toolcall | ✓ | ✓ | ✓ |
| json_multi_field | ✓ | ✓ | ✓ |
| instr_follow | ✓ | ✓ | ✓ |
| math_word | ✓ | ✓ | ✓ |
| math_2step | ✗ (50) | ✗ (55) | ✗ (75) |
| code_python | ✓ | ✓ | ✓ |
| extract | ✓ | ✓ | ✓ |
| summarize | ✗ (re-emits source) | ✗ (re-emits source) | ✓ (true compression) |
| negation | ✓ | ✓ | ✓ |
| Weights | 1.24 GB | 2.71 GB | 13.62 GB |

**Read of the data:**
- **math_2step is a hard wall for all three** (50/55/75 vs 100) — two-step arithmetic is genuinely beyond ≤4B dense and even 3B-active MoE.
- **2B and 4B are capability-identical on this suite** — the 4B buys nothing here and costs 2.5× the speed.
- **35B-A3B is the only one that truly summarizes** (8/9) but runs at 2.7 t/s — usable for batch, painful interactively.
- **2B at 7.7 t/s is the only interactive option** on this box while the GPU is held.

## 4. The "3.5B" question

**There is no 3.5B in the Qwen3.5 family.** Sizes: 0.8B / 2B / **4B** / 9B / 27B / 35B-A3B / 122B. The handoff doc's "target: 3.5B class" was aspirational. The real step up from 2B is **4B** — and on this machine it is *slower* with *no measurable capability gain* on the agent suite. The honest "bigger brain" is the **35B-A3B MoE** (3B active params → 27B-class quality, already on disk).

## 5. Replacement candidates (abliterated, measured or verified local)

| Model | Size | Where | Status |
|---|---|---|---|
| **Huihui-Qwen3.5-4B-abliterated Q4_K_M** | 2.71 GB | `~/.greylocalrag/models/` (downloaded this session) | benched — same pass rate, 2.5× slower |
| **Huihui-Qwen3.6-35B-A3B Opus-abl IQ3_XXS** | 13.62 GB | `~/models/huihui-qwen36-35b-opus-abliterated/` (already local) | benched — best quality, 2.7 t/s |
| Huihui-Qwen3.5-9B-abliterated Q4_K_M | ~5.5 GB | HF `mradermacher/Huihui-Qwen3.5-9B-abliterated-GGUF` | not benched (not expected to beat 4B on this suite) |
| Huihui-Qwen3.5-27B-abliterated | ~13 GB | HF `huihui-ai/Huihui-Qwen3.5-27B-abliterated-GGUF` | not local |
| Huihui-Qwen3.5-35B-A3B-abliterated (non-Opus) | ~13 GB | HF `huihui-ai/Huihui-Qwen3.5-35B-A3B-abliterated` | not local |

## 6. Recommendation

**Keep the 2B as the interactive default. Add the 35B-A3B as the "think hard" model.**

1. **2B stays on :7080** for the agent loop (tool calls, JSON actions, bash chains) — 7.7 t/s is the only interactive speed available while the GPU is held.
2. **35B-A3B as a second slot** (`--model .../Huihui-Qwen3.6-35B-A3B...gguf --port 7082 --ctx-size 32768`) for: summarize/digest tasks, research-library page rewrites, anything where 2.7 t/s is acceptable (batch).
3. **Do not switch the default to 4B** — measured identical pass rate at 2.5× the cost.
4. **Do not chase 9B/27B** — 2–3 t/s on CPU, and the 35B-A3B already dominates them on quality-per-tok/s.
5. **Fix the 2B's real weakness (looping) with the harness, not the model:** the handoff driver already owns the queue and edit guards; the 2B only emits one JSON action. That architecture is exactly right — the model's job is small enough that 2B-class is sufficient.

**Exact swap commands** (if the owner wants to test 4B or 35B-A3B as default):

```bash
# 4B as default (same slot, CPU):
# replace MODEL_PATH in build/src/server.py with:
#   /home/grey/.greylocalrag/models/Huihui-Qwen3.5-4B-abliterated-Q4_K_M.gguf
# then: greylocalrag   (launcher picks up the new path)

# 35B-A3B as a SECOND model (batch/think-hard slot):
cd ~/greylocalrag && nohup env LD_LIBRARY_PATH="$PWD/vendor/greymini-server" \
  CUDA_VISIBLE_DEVICES="" vendor/greymini-server/greymini-server \
  --model /home/grey/models/huihui-qwen36-35b-opus-abliterated/Huihui-Qwen3.6-35B-A3B-Claude-4.7-Opus-abliterated.i1-IQ3_XXS.gguf \
  --host 127.0.0.1 --port 7082 --ctx-size 32768 --n-gpu-layers 0 --threads 8 \
  --flash-attn off --reasoning off --jinja --alias greylocalrag --metrics \
  > state/model-boot-7082.log 2>&1 &
```

## 7. Best use for greylocalrag (the "perfect use")

**The research-library audit driver** (`handoff/library-agent.py`) is the perfect fit, and it's already built:

- The driver owns the queue (22 subgroups, 87 module pages, reverse-order), the edit guards (append-only + exact-unique-match removals, `.bak` before every write), the state (`state.json` resumable), and the audit (`AUDIT/audit.py`, currently **0 violations / 132 pages**).
- The model's job is **one JSON action per turn** — exactly the shape of task the 2B passes 7/9 of.
- At 7.7 t/s and ~50 tokens per action, one page takes ~30–60 s of model time. The remaining 87-module backlog is a multi-hour batch job — perfect for the 2B, and the 35B-A3B slot can handle the "rewrite this page's prose" sub-tasks where summarize quality matters.

**Not a good fit:** free-form chat, multi-step math, anything needing >8k context held in mind (the NSCE.gov loop was exactly this failure).

---

## Files

| File | Path |
|---|---|
| This audit | `~/greylocalrag/AUDIT.md` |
| Comparison doc + charts | `~/greylocalrag/COMPARISON.md` |
| Bench harness | `~/greylocalrag/state/bench/model_bench.py` |
| Bench results (JSON) | `~/greylocalrag/state/bench/qwen{2b,4b,35b}.json` |
| Charts (PNG) | `~/greylocalrag/state/bench/chart-{speed,tasks,tradeoff,ram}.png` |
| Chart generator | `~/greylocalrag/state/bench/make_charts.py` |
| Boot logs | `~/greylocalrag/state/bench/boot-{4444,4445,4446}.log` |
| 4B model (new) | `~/.greylocalrag/models/Huihui-Qwen3.5-4B-abliterated-Q4_K_M.gguf` |
