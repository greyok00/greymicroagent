# greylocalrag audit + model-fit plan (2026-10-27)

Owner ask: audit greylocalrag, find its perfect use, 2B vs 3.5B in real terms with charts,
deep comparison, find abliterated replacement models (some already local).

## Steps
1. [x] Inventory: 62GB RAM/26 free, i7-12800H 20t, A4500 16GB (15.4GB held by greyagent 27B). Local abliterated: 2B (1.24GB, in use), 35B-A3B Opus IQ3_XXS (13.6GB), 27B Q3_K_XL (13.3GB). Ollama :11600 has qwen3.5-abliterated:2b + qwen3-vl-abliterated:2b (blobs empty — not actually downloaded). NO 3.5B exists in the Qwen3.5 family — sizes are 0.8/2/4/9/27/35B-A3B/122B → real comparison is 2B vs 4B.
2. [x] Code audit: launcher slot allocation (7080/7081 + 4444-4447 pairs) sound; port_policy.json correct; settings.json sane (quietStartup, compaction reserve 8192); server.py ctx ladder 64k→32k floor, thinking off default (correct for 2B on CPU), NGL=0 CPU mode hides CUDA device; verify_compiled 95 lines; prompt file tight. Issues: port_policy says model_binary=vendor/llamacpp/ but actual path is vendor/greymini-server/ (stale doc); settings defaultThinkingLevel=balanced but server.py forces thinking off (mismatch, harmless); bench shows 2B at 2.2 t/s under GPU contention.
3. [x] Behavior audit (9 sessions, 2026-10-25): 580 tool calls (359 bash, 11 write, 7 read, 4 edit, 8 clickworker MCP), 0 tool errors. Real failures: owner-reported looping ("WHY ARE YOU LOOPING"), NSCE.gov hallucination repeated 4x after being told to remove it, empty-reply class (documented in server.py), instruction drift (re-wrote handoff kit 3x). Strengths: valid tool-call JSON, long bash chains, ClickWorker tick loop ran clean (8 turns, correct status report).
4. [x] 2B bench (CPU, :4444): 2.2 t/s under contention, pass_rate 0.667 (6/9): PASS json_toolcall, json_multi_field, math_word, extract, summarize, negation; FAIL instr_follow (word/sentence rules), math_2step (50+50=100s? got wrong), code_python (fib). Full JSON in state/bench/qwen2b.json
5. [x] 4B abliterated (Huihui-Qwen3.5-4B Q4_K_M, 2.71GB) benched on :4446; 35B-A3B benched on :4445. Fixed-harness results: 2B 7.7t/s 7/9, 4B 3.1t/s 7/9, 35B-A3B 2.7t/s 8/9. 2B and 4B capability-identical; 35B-A3B only one that summarizes. math_2step fails all three.
6. [ ] greysearch research: best abliterated 2-4B GGUFs (huihui et al.) + verify local 35B-A3B / 27B abliterated fit the 16GB card incl. KV
7. [ ] Charts (PNG + HTML): speed, capability matrix, VRAM/RAM fit, cost-per-task
8. [ ] Write AUDIT.md + COMPARISON.md + recommendation (perfect use + exact swap commands)
9. [ ] Memory: persist findings; final owner summary

## Rules
- Never kill greyagent's server (pid 223763, :7080/:7081, 15.4GB VRAM).
- greylocalrag test boots use slot 4444/4454+, NGL=0 unless VRAM check passes.
- All bench numbers measured on THIS machine, never quoted from memory.
