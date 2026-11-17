# 2B vs 4B vs 35B-A3B — measured comparison

All numbers **live-measured on this machine** (i7-12800H, CPU-only, NGL=0, 8 threads, ctx 8192). No quoted-from-memory figures. Harness: `state/bench/model_bench.py` (9-task agent suite + 60-token speed count).

> **The 3.5B that doesn't exist:** the Qwen3.5 family has no 3.5B — sizes are 0.8/2/4/9/27/35B-A3B/122B. So the real question is *2B vs 4B* (the next step up) and *vs the 35B-A3B MoE* (the "bigger brain" already on disk).

---

## Speed

![decode speed](state/bench/chart-speed.png)

The 2B is **2.5× faster than the 4B** and **2.8× faster than the 35B-A3B**. On a CPU with the GPU held, decode speed *is* the user experience — 7.7 t/s is interactive, 3.1 t/s is "wait for it", 2.7 t/s is batch.

## Capability

![task matrix](state/bench/chart-tasks.png)

| Task | 2B | 4B | 35B-A3B |
|---|:---:|:---:|:---:|
| json_toolcall | ✓ | ✓ | ✓ |
| json_multi_field | ✓ | ✓ | ✓ |
| instr_follow | ✓ | ✓ | ✓ |
| math_word | ✓ | ✓ | ✓ |
| math_2step | ✗ 50 | ✗ 55 | ✗ 75 |
| code_python | ✓ | ✓ | ✓ |
| extract | ✓ | ✓ | ✓ |
| summarize | ✗ | ✗ | ✓ |
| negation | ✓ | ✓ | ✓ |
| **Pass rate** | **7/9** | **7/9** | **8/9** |

Two real ceilings, both model-class not quantization:
- **math_2step** — all three fail (50/55/75 vs 100). Two-step arithmetic is beyond ≤4B dense *and* 3B-active MoE.
- **summarize** — 2B and 4B both *re-emit the source sentence* instead of compressing; only the 35B-A3B genuinely summarizes.

**The headline: 2B and 4B are capability-identical on this suite.** The 4B buys zero pass-rate and costs 2.5× the speed.

## The trade-off, in one picture

![speed vs capability](state/bench/chart-tradeoff.png)

The 2B sits top-left of the *interactive* region (≥3 t/s) with the same pass rate as the 4B. The 35B-A3B is the only one that clears the summarize bar, but it's in the batch region.

## RAM footprint (all fit in 26 GB free)

![ram footprint](state/bench/chart-ram.png)

| Model | Weights | RAM-free? | GPU-alone (16 GB)? |
|---|---|:---:|:---:|
| 2B Q4 | 1.24 GB | ✓ | ✓ |
| 4B Q4_K_M | 2.71 GB | ✓ | ✓ |
| 35B-A3B IQ3_XXS (MoE) | 13.62 GB | ✓ | ✗ (15.4 GB held) |
| 27B Q3_K_XL | 13.33 GB | ✓ | ✗ |

Everything fits in RAM. The 35B-A3B and 27B *could* run on the A4500 if the GPU were free, but it isn't — so they're CPU-only, which is exactly why the MoE's 3B-active design matters (it decodes at ~2.7 t/s, close to a 2B, despite 35B total params).

---

## Bottom line

- **Interactive default → 2B.** Fastest, same pass rate as 4B, the only interactive option while the GPU is held.
- **Think-hard / batch → 35B-A3B.** The only one that summarizes; 2.7 t/s is fine for the research-library rewrite backlog.
- **Skip the 4B** for this job — measured no gain, 2.5× slower.
- **The 2B's real failure is looping, not capability** — fix it in the harness (the handoff driver already isolates the model to one JSON action/turn), not by swapping models.
