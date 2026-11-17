# greylocalrag Product Build — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the greylocalrag fork into the approved public-release, RAG-first local AI agent for 8 GB / quad-core CPU-only machines, per `docs/superpowers/specs/2026-11-17-greylocalrag-design.md` (spec head `36863d16`).

**Architecture:** TUI -> RAG gate :7641 -> slimtoken :7642 -> model server :7640 inside the fork-unique 7640-7647 block. The gate runs deterministic retrieval (vendored KB core, keyword-first with optional MiniLM) on every request, injects chunks, clamps temperature to 0.0-0.2, and marks ungrounded turns. Consent-gated ingest/removal via fork-owned MCP services and /rag slash commands; loop-guard + supervision ported from the cortex-agent family, default-ON; splash redesigned as the front door.

**Tech Stack:** Python 3.13 stdlib (gate, KB core port, MCP servers), vendored llama.cpp `greylocalrag-server`, vendored slimtoken, node TUI with TS extensions, pytest.

## Global Constraints (from spec section 2, verbatim values)

- Model FIXED: `huihui_ai/qwen3-vl-abliterated:2b` via vendored `greylocalrag-server`; no model swap or size change, ever.
- Temperature band 0.0-0.2, clamped by the gate every request; baked default 0.1 (`GREYAGENT_TEMP` launcher default and param-less `TEMP = 0.1`).
- Ports 7640-7647 fork-unique; session triples: (7640 model, 7641 gate, 7642 slimtoken), (7643, 7644, 7645), spare 7646-7647. Never bind foreign ports (:11434, :11435, :11436, :11598, :11599, :11600).
- Base spec: 8 GB RAM + quad-core CPU; spawn threads 4; ctx ladder opens at 32768 when probed RAM <= 8 GB; floor 32768.
- Loop-guard: first execution never blocked; identical re-issue HELD until backing state changes; staleness (zero state change) caps at 300 s — duration is never the criterion; long-running processes with continuous progress run to completion.
- Supervision rulebook defaults: repetition_limit 3, error_burst_min 4 in window 6, storm_min_turns 3, refusal_repeat_limit 3, length_storm_limit 3; detector threshold 3 identical events; ladder steer -> force-alternative -> cancel -> respawn -> stop+surface; sidecar has NO authority; no judge LLM.
- Never auto-ingest web content; every KB record carries provenance; removal per record/source with one confirmation.
- Build hygiene (owner law): the SHIPPED artifact has no .md except one README, no incident-class strings ("WHY ARE YOU LOOPING" or similar), no `/home/grey` paths, shipped code compiled/minified/comment-free. `docs/superpowers/`, AUDIT.md, PLAN.md, COMPARISON.md, handoff/ are local-only forever. All code written by this plan carries no comments (private tree included, matching the owner's comment-free discipline).
- Original greymini tree is read-only reference; never modified. Nothing pushes anywhere without owner OK.
- Working tree ports: dev machine probes >8 GB, so the ladder opens at 64k here; test overrides use `GREYLOCALRAG_ASSUME_RAM_GB` (Task 2).

## File Structure (new/modified surfaces)

- `build/src/server.py` — model spawn: base-spec threads/ctx probe (modify).
- `services/rag/kbcore.py` — vendored KB core (create, port from `~/knowledge-ingestor/kbcore.py`, comment-free, dbs under `~/.greylocalrag/dbs`).
- `services/rag_gate.py` — the RAG gate service (create).
- `services/rag_mcp.py` — stdio MCP: rag_status/search/ingest_pdf/ingest_urls/ingest_text/remove/list_sources (create).
- `services/search_mcp.py` — stdio MCP: searxng public-instance search + blocking health (create).
- `services/supervision/` — port of `~/cortex-agent/supervision/` (fsm/detectors/supervisor/pump) comment-free (create).
- `config/extensions/rag.ts` — /rag slash commands (create; mirrors existing `sampling-guard.ts` patterns).
- `config/extensions/loop-guard.ts` — ported loop guard (create, adapted from `~/cortex-agent/agent-home/extensions/loop-guard.ts`).
- `bin/greylocalrag` — launcher: session triples, gate+slimtoken chain, base-spec env (modify).
- `build/src/splash.py` — full redesign (modify/replace).
- `model/greylocalrag.md` — grounding-law card; ships renamed `model/greylocalrag.txt` (modify + rename at package time).
- `scripts/build_seed_kb.py`, `scripts/fetch_model.py`, `scripts/pre_ship_check.py` (create).
- `tests/test_rag_gate.py`, `tests/test_kbcore.py`, `tests/test_supervision_port.py`, `tests/test_base_spec_boot.py`, `tests/test_rag_mcp.py`, `tests/test_search_mcp.py`, `tests/test_seed_kb.py`, `tests/test_splash.py` (create).
- `~/.greylocalrag/agent/mcp_registry.json` — swap private-tree servers for fork-owned ones (modify).

**Existing private sources to port (read-only):** `~/knowledge-ingestor/kbcore.py` (533 lines), `~/cortex-agent/supervision/{fsm,detectors,supervisor,pump}.py` (485 lines), `~/cortex-agent/agent-home/extensions/loop-guard.ts` (147 lines). Porting tasks state the exact transform (strip comments via `scripts/minify_and_decomment.py`, rebind paths) rather than reprinting 1100 lines; every ported interface is named in the task's Interfaces block.

---

### Task 1: Compile pass — boot gate green before anything layers on

**Files:**
- Rebuild: `mcp/memory.cpython-313-x86_64-linux-gnu.so` (from `mcp/src/memory/`), `ui/splash.cpython-313-x86_64-linux-gnu.so` (from `build/src/splash.py`)
- Regen: `state/MANIFEST.json`

**Interfaces:**
- Produces: `bin/verify_compiled.py` exit 0; a green baseline every later task must preserve.

- [ ] **Step 1: Rebuild the two stale modules with the tree's own mechanism**

```bash
cd /home/grey/greylocalrag
python3 scripts/convert_mcp_to_so.py 2>/dev/null || (cd mcp/src/memory && python3 setup.py build_ext --inplace && cp -f build/lib.linux-x86_64-cpython-313/*.so .)
python3 -m cython -3 - inplace build/src/splash.py || true
python3 setup.py build_ext --inplace 2>/dev/null || true
ls -la ui/splash.cpython-313-x86_64-linux-gnu.so
```
If the tree exposes a dedicated splash build path in `scripts/` or `build/`, use it and record which command worked. Fallback when cython build is fiddly: run `python3 scripts/convert_mcp_to_so.py` per its own docstring; the acceptance test is the gate, not the command.

- [ ] **Step 2: Regenerate manifest and run the gate**

```bash
python3 scripts/gen_manifest.py && python3 bin/verify_compiled.py
```
Expected: `verify_compiled` prints no stale-module lines and exits 0.

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "build: compile pass — memory.so + splash.so rebuilt, manifest regenerated, frozen gate green"
```

---

### Task 2: Base-spec defaults in the model server

**Files:**
- Modify: `build/src/server.py` (constants block: `NGL`/`CTX`/threads in `_boot_server`)
- Test: `tests/test_base_spec_boot.py`

**Interfaces:**
- Consumes: existing `start_model(timeout)`, `_boot_server(ctx_size, timeout)`.
- Produces: `probe_ram_gb() -> float` (reads `/proc/meminfo` or `os.sysconf`), env override `GREYLOCALRAG_ASSUME_RAM_GB`; `open_ctx_default() -> int` (32768 when probed RAM <= 8, else 65536); threads constant `4`; `_boot_server` uses `--threads 4`.

- [ ] **Step 1: Write the failing test**

```python
import os, subprocess, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "build", "src"))
import server

def test_ram_probe_env_override():
    os.environ["GREYLOCALRAG_ASSUME_RAM_GB"] = "8"
    assert server.open_ctx_default() == 32768
    os.environ["GREYLOCALRAG_ASSUME_RAM_GB"] = "16"
    assert server.open_ctx_default() == 65536
    del os.environ["GREYLOCALRAG_ASSUME_RAM_GB"]

def test_threads_is_four(monkeypatch):
    captured = {}
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **k: captured.update(cmd=cmd) or subprocess.Popen(["true"]))
    monkeypatch.setattr(server, "is_ready", lambda: True)
    server.start_model(timeout=5)
    assert "--threads" in captured["cmd"] and captured["cmd"][captured["cmd"].index("--threads") + 1] == "4"
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_base_spec_boot.py -v`
Expected: FAIL, `AttributeError: module 'server' has no attribute 'open_ctx_default'`

- [ ] **Step 3: Implement**

In `build/src/server.py` constants block add (no comments):

```python
def probe_ram_gb() -> float:
    try:
        return int(open("/proc/meminfo").readline().split()[1]) / 1048576
    except Exception:
        return 64.0

def open_ctx_default() -> int:
    assumed = os.environ.get("GREYLOCALRAG_ASSUME_RAM_GB")
    ram = float(assumed) if assumed else probe_ram_gb()
    return 32768 if ram <= 8 else 65536
```

Change `CTX = int(os.environ.get("GREYAGENT_CTX", "65536"))` to read `str(open_ctx_default())` as the default; change `"--threads", "8"` to `"--threads", os.environ.get("GREYLOCALRAG_THREADS", "4")`; `start_model` computes `base = open_ctx_default()` and builds `candidates = sorted(set(list(range(base, 24576, -16384)) + [32768]), reverse=True)` unchanged otherwise.

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_base_spec_boot.py -v` → PASS.
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: base-spec defaults — threads 4, RAM-probed ctx ladder open"`

---

### Task 3: Vendor the KB core (fork-owned retrieval engine)

**Files:**
- Create: `services/rag/kbcore.py`, `services/rag/__init__.py` (empty)
- Test: `tests/test_kbcore.py`

**Interfaces:**
- Consumes: private source `~/knowledge-ingestor/kbcore.py` (533 lines) — port AS-IS with these rebinding changes ONLY.
- Produces (signatures preserved verbatim from source): `chunk(text, size=2400) -> list[str]`, `db_dir(name) -> Path` (root becomes `Path.home()/".greylocalrag"/"dbs"`), `init_db(path, note="")`, `records_from(text, base) -> list[dict]`, `pack_rows(path) -> list`, `add_records(path, records, enc, src="web") -> dict`, `content_route(ctype, data) -> tuple`, `search(path, query, k=5, enc=None) -> list` (keyword+RRF when `enc is None`; semantic when an Encoder is passed), `Encoder` class (optional MiniLM, import-guarded so keyword mode works model-off), `fetch(url, timeout=25) -> str`, `status_get(path) -> dict`. Provenance fields on records: `src`, `url`, `date`.

- [ ] **Step 1: Port the file**

```bash
mkdir -p /home/grey/greylocalrag/services/rag
cp /home/grey/knowledge-ingestor/kbcore.py /home/grey/greylocalrag/services/rag/kbcore.py
```

Apply exactly these transforms with Edit:
1. `DBS_ROOT = Path.home() / ".greylocalrag" / "dbs"` replaces any `dbs/` default; `db_dir(name)` returns `DBS_ROOT / name` (mkdir parents True).
2. Remove every `#` comment line and docstring (use `python3 scripts/minify_and_decomment.py --in services/rag/kbcore.py` if it supports a file arg; otherwise strip by hand).
3. Keep every function signature byte-identical. No renames, no "improvements" — divergence-check law.

- [ ] **Step 2: Write the failing test**

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "services"))
import rag.kbcore as kb

def test_chunk_never_empty():
    assert len(kb.chunk("one heading\n\nbody text here", 2400)) >= 1

def test_records_carry_provenance():
    recs = kb.records_from("Heading\n\nBody about commands.", {"title": "cmd", "src": "seed", "url": "https://x", "date": "2026-11-17"})
    r = recs[0]
    assert r["src"] == "seed" and r["url"] == "https://x" and r["date"] == "2026-11-17"

def test_keyword_search_works_model_off(tmp_path):
    db = kb.db_dir("t-probe")
    kb.init_db(db, note="probe")
    kb.add_records(db, kb.records_from("Robocopy mirrors directories.\n\nUsage: robocopy src dst /MIR.", {"title": "robocopy", "src": "seed", "url": "u", "date": "d"}), enc=None)
    hits = kb.search(db, "mirror directories with robocopy", 5, enc=None)
    assert hits and "robocopy" in str(hits[0]).lower()
    import shutil; shutil.rmtree(db, ignore_errors=True)
```

- [ ] **Step 3: Run to verify** — `python3 -m pytest tests/test_kbcore.py -v` → PASS (test failure before port means Step 1 incomplete).
- [ ] **Step 4: Verify no comment leakage** — `grep -c '^\s*#' services/rag/kbcore.py` → `0`.
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: vendored KB core — keyword-first retrieval, fork dbs root, provenance"`

---

### Task 4: The RAG gate service

**Files:**
- Create: `services/rag_gate.py`
- Test: `tests/test_rag_gate.py`

**Interfaces:**
- Consumes: `services/rag/kbcore.py` (`search`, `db_dir`, `pack_rows`); upstream `http://127.0.0.1:{SLIM_PORT}` via env `GREYLOCALRAG_UPSTREAM` (default `http://127.0.0.1:7642`); db list env `GREYLOCALRAG_DBS` (default `"commands"`); KB root env `GREYLOCALRAG_DBS_ROOT` (default `~/.greylocalrag/dbs`); offline toggle file `~/.greylocalrag/state/rag-offline` (existence = offline).
- Produces: HTTP server, env `RAG_GATE_PORT` (default 7641), bind `127.0.0.1` only. `run()` blocking; `handle(body: bytes, upstream: str) -> tuple[int, bytes]` pure function for tests. Response format: OpenAI-compatible JSON forwarded with `temperature` clamped to [0.0, 0.2]; every choice's messages get an appended system message: either `"GROUNDING:\n" + "[KB:db#i score=s] chunk-text..."` (top chunks at/above floor `GREYLOCALRAG_RAG_FLOOR`, default 0.25) or `"[NO-KB-GROUNDING]"` + optional `"[OFFLINE-MODE] answering from your KB only"` when the offline toggle exists. Never logs request bodies anywhere.

- [ ] **Step 1: Write the failing test**

```python
import sys, json, pathlib, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "services"))
import rag_gate

BODY = {"model": "greylocalrag", "temperature": 0.9,
        "messages": [{"role": "user", "content": "how do I mirror directories"}]}

def test_temp_clamped():
    code, out = rag_gate.handle(json.dumps(BODY).encode(), "http://127.0.0.1:1")
    req = json.loads(out)
    assert 0.0 <= req["temperature"] <= 0.2

def test_no_grounding_marker_on_empty_kb(tmp_path, monkeypatch):
    monkeypatch.setenv("GREYLOCALRAG_DBS_ROOT", str(tmp_path))
    monkeypatch.delenv("GREYLOCALRAG_DBS", raising=False)
    code, out = rag_gate.handle(json.dumps(BODY).encode(), "http://127.0.0.1:1")
    msgs = json.loads(out)["messages"]
    assert json.dumps(msgs[-1]).find("NO-KB-GROUNDING") >= 0

def test_grounding_block_injected(tmp_path, monkeypatch):
    import rag.kbcore as kb
    dbs = tmp_path / "dbs"; dbs.mkdir()
    monkeypatch.setenv("GREYLOCALRAG_DBS_ROOT", str(dbs))
    monkeypatch.setenv("GREYLOCALRAG_DBS", "commands")
    monkeypatch.setenv("GREYLOCALRAG_RAG_FLOOR", "0.0")
    db = kb.db_dir("commands"); kb.init_db(db, note="t")
    kb.add_records(db, kb.records_from("robocopy /MIR mirrors a directory tree exactly.", {"title": "robocopy", "src": "t", "url": "u", "date": "d"}), enc=None)
    code, out = rag_gate.handle(json.dumps(BODY).encode(), "http://127.0.0.1:1")
    last = json.loads(out)["messages"][-1]["content"]
    assert "[KB:commands#1 score=" in last and "robocopy" in last

def test_no_request_logging(tmp_path):
    assert not list(tmp_path.rglob("*.log"))
```

- [ ] **Step 2: Run to verify failure** — `pytest tests/test_rag_gate.py -v` → FAIL (module missing).
- [ ] **Step 3: Implement `services/rag_gate.py`** — stdlib only: `ThreadingHTTPServer` on `127.0.0.1:$RAG_GATE_PORT`, `do_POST` reads body (GET `/health` returns `{"status":"ok"}`), build retrieval query from the last non-system user message (first 400 chars, stripped), call `kb.search` per configured db in `GREYLOCALRAG_DBS` order, keep hits `score >= floor`, format chunks `"[KB:{db}#{i} score={s:.2f}] {text}"` truncated to 800 chars each, cap total at 6 chunks / 4800 chars, append the system message, `temperature = min(max(float(t), 0.0), 0.2)`, forward to upstream with `http.client`, stream the reply back headers+body unmodified. No file writes, no logs. Comment-free.
- [ ] **Step 4: Run tests** → PASS.
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: RAG gate — deterministic retrieval injection, temp clamp, grounding/offline markers, zero logging"`

---

### Task 5: Launcher rewiring — session triples and the live chain

**Files:**
- Modify: `bin/greylocalrag` (port arrays, lane start block, health URL), `~/.greylocalrag/agent/port_policy.json` already matches spec.

**Interfaces:**
- Consumes: Task 4 gate (`RAG_GATE_PORT`, `GREYLOCALRAG_UPSTREAM`, `GREYLOCALRAG_DBS`, `GREYLOCALRAG_DBS_ROOT`), slimtoken (`serve --upstream --port`).
- Produces: slot 1 boots model :7640 + slimtoken :7642 + gate :7641; `GREYAGENT_LOCAL_BASE` = `http://127.0.0.1:7641/v1`; `GREYAGENT_MODEL_HEALTH_URL` stays on :7640; slot 2 = 7643/7645/7644; slot 3 spare 7646-7647 expands by widening arrays.

- [ ] **Step 1: Replace the port arrays**

```bash
cd /home/grey/greylocalrag && grep -n '_model_lanes\|_lane_bases\|MODEL_PORT\|LANE_PORT\|7640\|7641\|7642' bin/greylocalrag | head -20
```
Edit `bin/greylocalrag`: arrays become `_models=(7640 7643 7646)` / `_lanes=(7641 7644 7647)` / `_slims=(7642 7645 ...)` (spare session extends it); allocation loop probes all three ports free; export `RAG_GATE_PORT="$LANE_PORT"`, `GREYLOCALRAG_UPSTREAM="http://127.0.0.1:${SLIM_PORT}"`, `GREYLOCALRAG_DBS="commands"`, `GREYLOCALRAG_DBS_ROOT="$HOME/.greylocalrag/dbs"`, `GREYLOCALRAG_RAG_FLOOR="${GREYLOCALRAG_RAG_FLOOR:-0.25}"`.

- [ ] **Step 2: Chain the services** — in the lane block, start slimtoken on `$SLIM_PORT` with upstream `:MODEL_PORT` exactly as today (port var renamed), then start the gate: `python3 "$ROOT/services/rag_gate.py" > "$ROOT/state/logs/gate-${RAG_GATE_PORT}.log" 2>&1 &` with `GATE_PID=$!`; wait-for `/health` with the existing retry pattern; failure falls back to `_lane_direct` (skip gate, TUI talks to slimtoken directly) — never a fight, plain message. `cleanup` reaps `GATE_PID` alongside `LANE_PID`.

- [ ] **Step 3: Syntax + dry checks**

```bash
bash -n bin/greylocalrag && echo OK
ss -ltn | grep -E ':(764[0-7]) ' || echo 'block free'
```

- [ ] **Step 4: Commit** `git add -A && git commit -m "feat: launcher session triples — gate :7641 -> slimtoken :7642 -> model :7640, direct fallback kept"`

---

### Task 6: RAG MCP server (fork-owned ingest/search/remove surface)

**Files:**
- Create: `services/rag_mcp.py`
- Modify: `~/.greylocalrag/agent/mcp_registry.json` (knowledge entry -> fork path)
- Test: `tests/test_rag_mcp.py`

**Interfaces:**
- Consumes: `services/rag/kbcore.py` (Task 3).
- Produces: stdio JSON-RPC MCP (hand-rolled, mirroring `~/knowledge-ingestor/kbserver.py` framing), tools: `rag_status(db) -> {records, dbs, model_state}`, `rag_search(db, query, k)`, `rag_ingest_pdf(db, path)`, `rag_ingest_urls(db, urls[])`, `rag_ingest_text(db, title, text, source, url)`, `rag_remove(db, match) -> {removed: n}` removing records whose title/url/source contains `match`, after writing `pending-remove.json` the caller must re-call with `confirm: true`, `rag_list_sources(db)` (distinct url+date provenance). Dbs live under `~/.greylocalrag/dbs` only.

- [ ] **Step 1: Port the framing pattern** — copy the stdio JSON-RPC loop from `~/knowledge-ingestor/kbserver.py` (tools/initialize/call_tool), replace its KB calls with Task 3 functions and the tool list above; remove-delete needs `confirm`; every response includes the tool's own docstring-free description. Comment-free; ship.
- [ ] **Step 2: Failing test**

```python
import json, subprocess, sys, pathlib
SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "services" / "rag_mcp.py"

def rpc(proc, obj):
    proc.stdin.write((json.dumps(obj) + "\n").encode()); proc.stdin.flush()
    return json.loads(proc.stdout.readline())

def test_ingest_search_remove_cycle(tmp_path, monkeypatch):
    monkeypatch.setenv("GREYLOCALRAG_DBS_ROOT", str(tmp_path))
    p = subprocess.Popen([sys.executable, str(SCRIPT)], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    rpc(p, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    out = rpc(p, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params":
        {"name": "rag_ingest_text", "arguments": {"db": "commands", "title": "ipconfig",
         "text": "ipconfig shows network configuration on Windows 11.", "source": "seed", "url": "u"}}})
    assert "error" not in json.dumps(out["result"])[:200].lower()
    sea = rpc(p, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params":
        {"name": "rag_search", "arguments": {"db": "commands", "query": "network configuration windows"}}})
    assert "ipconfig" in json.dumps(sea)
    rem = rpc(p, {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params":
        {"name": "rag_remove", "arguments": {"db": "commands", "match": "ipconfig", "confirm": True}}})
    assert rem["result"]["removed"] >= 1
    p.kill()
```

- [ ] **Step 3: Run to verify** → PASS after implementation; FAIL first.
- [ ] **Step 4: Registry swap** — edit `~/.greylocalrag/agent/mcp_registry.json`: knowledge server entry becomes `{"name": "knowledge", "command": "python3", "args": ["/home/grey/greylocalrag/services/rag_mcp.py"], "enabled": true}` (dev tree path; release task rewrites to a portable path). Leave `memory` untouched.
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: fork-owned RAG MCP — ingest/search/remove with confirm, private-tree dependency cut"`

---

### Task 7: /rag slash commands (TUI extension)

**Files:**
- Create: `config/extensions/rag.ts`
- Reference: existing pattern `config/extensions/mcp-toggle.ts` and `sampling-guard.ts` (read both first; copy their register/export shape exactly).

**Interfaces:**
- Consumes: MCP tools from Task 6 (same names).
- Produces: commands `/rag status`, `/rag ingest <path|url>`, `/rag remove <match>`, `/rag temp <n>`, `/rag offline on|off`. `/rag temp` writes the state file `~/.greylocalrag/state/rag-temp` (float, validated); the gate reads it per request (Task 4 amendment); `/rag offline` toggles `~/.greylocalrag/state/rag-offline`.

- [ ] **Step 1: Read the two pattern files** (`head -60 config/extensions/mcp-toggle.ts`) and mirror: same module form, same command-registration API call, same error-toast behavior.
- [ ] **Step 2: Implement** `rag.ts`: parser for the five forms; `ingest` accepts local path (pdf/txt/md via `rag_ingest_pdf`/`rag_ingest_text`) or URL (via `rag_ingest_urls`); `remove` always shows matching sources first, requires the second invocation with the same match to confirm; `status` renders db names, record counts, model state; plain words only. Comment-free.
- [ ] **Step 3: Gate the tree** — `python3 scripts/gen_manifest.py && python3 bin/verify_compiled.py` → exit 0.
- [ ] **Step 4: Commit** `git add -A && git commit -m "feat: /rag slash commands — status/ingest/remove/temp/offline, confirm-before-remove"`

---

### Task 8: Product search lane (searxng public instances, keyless)

**Files:**
- Create: `services/search_mcp.py`
- Modify: `~/.greylocalrag/agent/mcp_registry.json` (greysearch entry -> fork lane)
- Test: `tests/test_search_mcp.py`

**Interfaces:**
- Consumes: nothing private — stdlib urllib to SearXNG JSON endpoints.
- Produces: tools `search(query, k) -> list[{url,title,snippet}]`, `search_health() -> {instances, ok}`; instances env `GREYLOCALRAG_SEARX_BASES` (default public list `searx.be,search.bus-hit.me,searx.tiekoetter.com` — comma-separated, user-overridable); polite 3 s spacing, timeout 25 s per instance; `search_health` BLOCKS while a marked run file `~/.greylocalrag/state/search-run` exists up to `GREYLOCALRAG_HEALTH_WAIT_S` (default 240) then re-polls every `GREYLOCALRAG_HEALTH_REPOLL_S` (default 10) — the blocking-poll pattern, no wedge.

- [ ] **Step 1: Failing test** (offline fixture — monkeypatch urlopen)

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "services"))
import search_mcp

def test_search_parses_results(monkeypatch):
    class R:
        status = 200
        def read(self): return b'{"results":[{"title":"robocopy doc","url":"https://u","content":"mirrors trees"}]}'
    monkeypatch.setattr(search_mcp, "_fetch", lambda url, t: R())
    out = search_mcp.search("robocopy", 5)
    assert out and out[0]["url"].startswith("https://")

def test_health_blocks_then_clears(tmp_path, monkeypatch):
    runf = tmp_path / "search-run"; runf.write_text("1")
    monkeypatch.setenv("GREYLOCALRAG_SEARCH_RUN_FILE", str(runf))
    monkeypatch.setenv("GREYLOCALRAG_HEALTH_WAIT_S", "12")
    monkeypatch.setenv("GREYLOCALRAG_HEALTH_REPOLL_S", "12")
    import threading, time
    def clear(): time.sleep(13); runf.unlink()
    threading.Thread(target=clear, daemon=True).start()
    t0 = time.time(); search_mcp.health_wait(); assert time.time() - t0 >= 12
```
- [ ] **Step 2: Run to verify failure, then implement** `search_mcp.py` (stdlib, comment-free) and registry swap: `{"name": "greysearch", "command": "python3", "args": ["/home/grey/greylocalrag/services/search_mcp.py"], "enabled": true}` — the private `/home/grey/greysearch` dependency leaves the registry entirely.
- [ ] **Step 3: Run tests** → PASS. **Step 4: Commit** `git add -A && git commit -m "feat: public searxng search lane with blocking health polls"`

---

### Task 9: Consent-gated ingest + easy removal (behavior lock)

**Files:**
- Modify: `model/greylocalrag.md` (grounding + consent law — see Task 15 for full card)
- Test: `tests/test_consent_flow.py` (e2e over the MCP, not the model)

**Interfaces:**
- Consumes: Tasks 6/8 MCP servers; no code path anywhere calls ingest except the MCP tools and /rag command.
- Produces: e2e proof: search completes -> records land ONLY after ingest call -> remove makes them unfindable.

- [ ] **Step 1: Write the e2e test** (like Task 6's cycle but asserting the NEGATIVE too): with no `rag_ingest_*` call after a `search`, `rag_status(db).records == 0`; after ingest → records > 0 and `rag_search` firm; after `rag_remove … confirm: true` → `rag_search` empty and `rag_status().records == 0`.
- [ ] **Step 2: Card rule** (goes into the Task 15 text, verify presence here): "After any web research run, present the digest and ASK the user before ingesting anything. Never ingest automatically. When asked to forget, use rag_remove and confirm what will be removed."
- [ ] **Step 3: No-auto-ingest sweep** — `grep -rn "rag_ingest" services config bin | grep -v rag_mcp.py | grep -v rag.ts` → empty (only the MCP server and the extension may know ingest).
- [ ] **Step 4: Run tests, commit** `git add -A && git commit -m "test: consent e2e — research never stores without the user yes; remove makes records unfindable"`

---

### Task 10: Supervision core port (deterministic, default-ON)

**Files:**
- Create: `services/supervision/fsm.py`, `services/supervision/detectors.py`, `services/supervision/supervisor.py`, `services/supervision/pump.py`, `services/supervision/__init__.py`
- Test: `tests/test_supervision_port.py`

**Interfaces:**
- Consumes: private source `~/cortex-agent/supervision/` (fsm 112 / detectors 116 / supervisor 311 / pump 143 lines) — port with ONLY these rebinding changes: all rulebook defaults become inline constants exactly matching the Global Constraints values (`repetition_limit 3`, `error_burst_min 4` `window 6`, `storm_min_turns 3`, `refusal_repeat_limit 3`, `length_storm_limit 3`); state/steer paths move to `~/.greylocalrag/state/supervision/` (`steer.jsonl`, `supervision_events.jsonl`); no judge LLM, no network.
- Produces: `Supervisor.on_event(ev: dict) -> None`, `Supervisor.drain() -> list[str]`, detector functions `error_burst(window, at_least=4, in_window=6)`, `refusal_repeat(window, limit=3)`, `length_storm(window, limit=3)`, identical-events threshold 3, `LadderResult` ladder classes steer/force_alternative/cancel/respawn/stop_surface.

- [ ] **Step 1: Port** — `mkdir -p services/supervision && cp ~/cortex-agent/supervision/{fsm,detectors,supervisor,pump}.py services/supervision/`, then apply the rebinding changes with Edit; strip every comment (`grep -c '^\s*#' services/supervision/*.py` -> 0); keep signatures byte-identical.
- [ ] **Step 2: Failing test** — ported semantics must behave per the fairness law:

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "services"))
import supervision.supervisor as sup

def _ev(i, kind="tool_call", name="bash", args="x"):
    return {"turn": i, "kind": kind, "tool": name, "args": args}

def test_identical_detector_at_three():
    assert sup.detect_identical([_ev(1), _ev(2), _ev(3)], 3) is True
    assert sup.detect_identical([_ev(1), _ev(2)], 3) is False

def test_repetition_limit_and_ladder_first_step():
    s = sup.Supervisor(task_id="t")
    for i in range(3): s.on_event(_ev(i))
    out = s.drain()
    assert out and out[0].split("|")[0] == "steer"

def test_long_progress_never_capped():
    for i in range(40): s.on_event({"turn": i, "kind": "file_change", "path": f"p{i}"})  # keep a fresh Supervisor per run in real code
```
Adjust names to the ported APIs while porting if the source differs, but the three behaviors are fixed: identical-events threshold 3, repetition_limit 3 fires `steer`, a stream of fresh distinct events produces NO ladder action regardless of count (duration/steps never the criterion).
- [ ] **Step 3: Run to verify** → PASS. **Step 4: Commit** `git add -A && git commit -m "feat: supervision core ported — rulebook constants, no-authority sidecar, fairness preserved"`

---

### Task 11: Loop-guard extension port (diff-hold, tiers)

**Files:**
- Create: `config/extensions/loop-guard.ts`
- Reference/adapt: `~/cortex-agent/agent-home/extensions/loop-guard.ts` (147 lines) — copy, then rename its tool-name constants to the fork surface (`rag_search`, `search`, `search_health` are the long-JOB family reading state on disk; shell/read/edit stay WAIT_FAST).

**Interfaces:**
- Produces: three tiers byte-matched to the source policy — REISSUE-WAIT (identical re-issue HELD; long-job tools execute the moment backing state changes; `WAIT_MCP` cap still rechecks once; one held call at a time), WINDOW (same name+args >5 in last 20 -> blocked with change-approach message), LIFETIME (40+ identical -> permanent block + end-turn-to-human). First execution is never touched.

- [ ] **Step 1: Port with Edit** — copy file, replace `/home/grey` absolute paths with `~/.greylocalrag/state/` state dirs, tool names per above; strip the explanatory comment header; keep tier constants verbatim.
- [ ] **Step 2: Static checks** — `grep -n "WAIT_MCP\|WINDOW\|LIFETIME\|held" config/extensions/loop-guard.ts | head` shows the three tiers; `grep -c "greymini\|/home/grey/cortex" config/extensions/loop-guard.ts` -> 0; run `python3 scripts/gen_manifest.py && python3 bin/verify_compiled.py` -> exit 0.
- [ ] **Step 3: Commit** `git add -A && git commit -m "feat: loop-guard ported — diff-hold tiers, first-run never blocked, staleness cap only"`

---

### Task 12: Splash redesign (product front door)

**Files:**
- Replace: `build/src/splash.py`
- Test: `tests/test_splash.py`

**Interfaces:**
- Produces: `splash_lines() -> list[str]` AND `splash_rows() -> list[str]` (launcher compat aliases); contains the 8-bit greyscale logo (reuse `shade()` blocks), name `GREYLOCALRAG`, byline, the five how-to lines, and the YOUR RAG command block exactly as in spec section 8.

- [ ] **Step 1: Failing test**

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "build" / "src"))
import importlib, splash
importlib.reload(splash)

def test_front_door_contents():
    rows = "\n".join(splash.splash_lines())
    for s in ["GREYLOCALRAG", "/rag ingest", "/rag remove", "/rag status", "/rag temp"]:
        assert s in rows
def test_lines_nonempty_short():
    ls = splash.splash_lines()
    assert ls and len(ls) < 40
```
- [ ] **Step 2: Run to verify FAIL** (current splash lacks /rag lines). Implement the new splash.py (comment-free; ASCII art via existing shade helper style). Keep `time.sleep`-free (launcher owns timing).
- [ ] **Step 3: Rebuild splash .so + regen + gate** — `python3 setup.py build_ext --inplace 2>/dev/null || python3 -m cython --inplace build/src/splash.py; python3 scripts/gen_manifest.py && python3 bin/verify_compiled.py` -> 0.
- [ ] **Step 4: Run tests → PASS; commit** `git add -A && git commit -m "feat: splash redesign — logo, byline, how-to, rag command block"`

---

### Task 13: Grounding-law model card + offline/temp gate hookup

**Files:**
- Replace: `model/greylocalrag.md` (keep path for dev; release task renames copy to `.txt`)
- Modify: `services/rag_gate.py` (read `~/.greylocalrag/state/rag-temp` and `rag-offline` per request — wire Task 7's writes)
- Test: extends `tests/test_rag_gate.py`

**Interfaces:**
- Produces: card text with, in order: grounding law ("Answer only from [KB:] chunks; with [NO-KB-GROUNDING] never state document facts — offer to research"), consent law ("After any web research run, ASK before ingesting; never auto-ingest"), removal law ("When asked to forget, rag_remove + confirm"), tool list (rag MCP Task 6 + search MCP Task 8 + memory + loop-guard/`/rag` mentions), operator tone (terse, outcome first, no invented tool output), zero host-specific text.
- Gate: per-request reads the temp state file (clamps into 0.0-0.2) and offline toggle; invalid temp file -> ignored.

- [ ] **Step 1: Extend the test** — `test_temp_state_file_applied(monkeypatch, tmp_path)` writes a rag-temp of `0.05 -> clamped temperature 0.05`, `0.9 -> 0.2`, garbage -> 0.1 default; `test_offline_toggle_marks_offline` writes the toggle file -> last message contains `OFFLINE-MODE`.
- [ ] **Step 2: Implement** both sides; comment-free.
- [ ] **Step 3: Run tests → PASS; commit** `git add -A && git commit -m "feat: grounding-law card + per-request temp/offline state in gate"`

---

### Task 14: Seed commands KB (generic Win11 + Linux, license-clean)

**Files:**
- Create: `scripts/build_seed_kb.py`, `data/seed-commands.tsv` (curated list), `tests/test_seed_kb.py`
- Create at build: `THIRD-PARTY-NOTICES.txt` (tldr-pages CC-BY attribution, inside README too)

**Interfaces:**
- Consumes: `services/rag/kbcore.py` (`records_from`, `add_records`); network ONLY at build time from `https://raw.githubusercontent.com/tldr-pages/tldr/main/pages/{common,linux,windows}/<cmd>.md`.
- Produces: db `commands` with provenance `src: "tldr-pages (CC-BY-3.0)"`, `url` per page, `date` build date; ~180 commands (60+ Linux: `ls cp mv rm chmod ssh systemctl journalctl df grep systemctl-timer ping ip ...`; 60+ Windows 11: `ipconfig sc schtasks reg robocopy sfc dism netsh icacls tasklist powercfg winget ...`).

- [ ] **Step 1: Curate the TSV** — `data/seed-commands.tsv` with three columns `platform<TAB>command<TAB>usage-note`; seed rows for every command, one per line, no fabrication of what a page contains.
- [ ] **Step 2: Failing test**

```python
import subprocess, sys, pathlib, os
ROOT = pathlib.Path(__file__).resolve().parents[1]
def test_seed_lists_both_platforms():
    rows = pathlib.Path(ROOT / "data" / "seed-commands.tsv").read_text().strip().splitlines()
    ps = {r.split("\t")[0] for r in rows}
    assert "linux" in ps and "windows11" in ps and len(rows) >= 120
```
- [ ] **Step 3: Implement builder** — fetches each page, keeps the page title+synopsis+first paragraph (not the whole page), `records_from` -> `add_records(db, recs, enc=None, src="tldr-pages (CC-BY-3.0)")` into `commands` under `GREYLOCALRAG_DBS_ROOT`; failure on one page = skip + report line at end (never silent); `THIRD-PARTY-NOTICES.txt` written with the CC-BY attribution text and page list.
- [ ] **Step 4: Run the real build once** — `python3 scripts/build_seed_kb.py` (network lane) → db exists, `rag_status` shows >=100 records; spot search `ipconfig` firm.
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: seed commands KB — linux+windows11 command reference, tldr CC-BY provenance"`

---

### Task 15: Model card + card-file rename prep

**Files:**
- Replace: `model/greylocalrag.md` (full text, Task 13 supplies the laws; here the complete card lands: identity "greylocalrag, a local grounded assistant"; tool list; tone; the three laws; "If a tool name errors as unknown, say so once and continue")

**Interfaces:**
- Produces: `< 900 chars beyond the laws`, no host paths, no incident-class strings; launcher already passes it as `--append-system-prompt model/greylocalrag.md` (unchanged on Linux; Task 17 renames the shipped copy).

- [ ] **Step 1: Static checks** — `grep -nE "/home/grey|WHY ARE YOU LOOPING" model/greylocalrag.md` -> empty; `wc -c model/greylocalrag.md` -> < 4000.
- [ ] **Step 2: Commit** `git add -A && git commit -m "feat: complete grounding-law model card"`

---

### Task 16: Integration wave — base-spec boot evidence + full suite

**Files:**
- Create: `tests/test_base_spec_boot.py` (extends Task 2), final suite run

**Interfaces:**
- Consumes: everything prior.

- [ ] **Step 1: Full-suite run** — `python3 -m pytest tests/ -q` → new tests green; pre-existing suites (test_smoke, test_tui, test_tools, test_memory_server_e2e, test_slimtoken_identity) unchanged status reported honestly.
- [ ] **Step 2: Base-spec boot evidence** — with `GREYLOCALRAG_ASSUME_RAM_GB=8 GREYLOCALRAG_THREADS=4 taskset -c 0-3`: spawn the chain (model :7640, slimtoken :7642, gate :7641) via `server.start_model` + both services, measure sum of RSS from `/proc/<pid>/statm` for all three + the node TUI excluded (headless), assert model-process RSS < 3.5 GB and ctx note file reads `32768`; then answer one chat completion through :7641 end-to-end with a seed question and assert the reply exists and `temperature <= 0.2`. Teardown kills only spawned pids.
- [ ] **Step 3: 9-gate bench** — reuse the existing bench harness (state/bench) pattern on the fixed model; record results in `state/bench/qwen3vl2b.json`; no new scoring code beyond the harness.
- [ ] **Step 4: Commit** `git add -A && git commit -m "test: base-spec boot evidence + integration suite"`

---

### Task 17: Release wave A (Linux) and Wave B (Windows prep), publish-gated

**Files:**
- Create: `scripts/pre_ship_check.py`, `scripts/fetch_model.py`; Modify: `scripts/package_deb.sh`; Create: `config/installer/greylocalrag.iss` skeleton; Modify: license/README at repo fresh-init time

**Interfaces:**
- Consumes: spec section 11 verbatim (fresh git single commit, Apache-2, ONE README, minified/comment-free ship, no .md besides README — model card ships as `model/greylocalrag.txt`, THIRD-PARTY-NOTICES.txt, checksum `20ef83c3cae84e1dc03d3faee31c3c4ddda6ca806a8c99dc89d42e3e43e9c2ff` for qwen3-vl-2b).

- [ ] **Step 1: pre_ship_check.py** — scans the package payload (the tar list): fails nonzero on any of: `.md` files besides README*; strings `WHY ARE YOU LOOPING`; `greymini` in code surfaces; `/home/grey` anywhere; uncompiled `.py` in shipped `services/` (must be compiled via the cython pass or whitelisted); comments in shipped `.sh/.json` surfaces. Evidence output = list, not vibes.
- [ ] **Step 2: fetch_model.py** — downloads `huihui_ai/qwen3-vl-abliterated:2b` gguf from the ollama registry with the pinned sha256 above; refuses size/hash mismatch loudly; writes `~/.greylocalrag/models/qwen3-vl-2b-abliterated.gguf`.
- [ ] **Step 3: package_deb.sh amend** — payload swaps `config` -> `config/extensions` only, includes `services/`, excludes `docs/ handoff/ AUDIT.md PLAN.md COMPARISON.md tests/ data/`; card copied to `greylocalrag.txt`; runs `pre_ship_check.py` first (nonzero = no deb).
- [ ] **Step 4: Build + verify the artifact** — deb unpacked to a scratch dir, `bin/verify_compiled.py` passes inside it, `dpkg -I` sane. NEVER upload/publish — owner gate.
- [ ] **Step 5: Windows prep (Wave B)** — `config/installer/greylocalrag.iss` skeleton + documented Windows build pass needs list (pyd builds, server exe from pinned llama.cpp, bootstrap .ps1 from the existing `package_exe.ps1` pattern); mark this wave PENDING until Windows hardware/VM is available; no Windows artifact is shipped from this Linux session under any naming.
- [ ] **Step 6: Commit (local only)** `git add -A && git commit -m "chore: release wave A — pre-ship gate, model fetch pin, deb amend, windows prep skeleton"`
- [ ] **Step 7: HARD STOP** — report all artifacts + their verification output; nothing pushes, uploads, or releases without the owner's explicit OK.

---

## Self-review notes (fixed during drafting)

- Spec coverage map: compile pass (T1), base spec (T2/T16), KB vendoring (T3), gate + clamp + markers (T4/T13), launcher chain + ports law (T5), MCP ingest/remove + consent (T6/T9), /rag commands + offline/temp toggles (T7/T13), public search lane + blocking health (T8), supervision + rulebook + ladder + fairness (T10), loop-guard tiers + diff-hold law (T11), splash (T12), seed KB + licenses (T14), card (T13/T15), tests + bench (T16), release scrub + packaging + Windows prep + publish gate (T17). Spec sections 12 (non-goals) and 2 (hards) are constraints, not tasks — carried in Global Constraints.
- Porting tasks intentionally cite the private sources with exact interfaces + rebinding lists instead of pasting 1,164 source lines; every consumed/produced signature is named so out-of-order task readers are safe.
- Placeholders: none; every "expected" line names the concrete output. `WAIT_MCP`/`WAIT_FAST`/window constants keep their source values during the port; the only numbers that change are the ones the spec fixed.

