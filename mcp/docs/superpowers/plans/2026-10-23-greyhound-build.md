# Greyhound Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Assemble `~/greyhound` as a fresh, self-contained, LLM-free deep-research repo (engine from the greyhound fork) exposing the canonical greysearch 2-tool MCP API, plus a full-run CLI and the hostable portal — verified live end to end.

**Architecture:** One engine (`deep_run`) faces three surfaces: stdio MCP (`greyhound_mcp.py`), CLI (`research.py`), Flask portal (`portal/`). The engine, SearXNG (:8890), browser slots (9351-9354), registry, and guides output all live inside the repo; zero references to foreign repos/ports.

**Tech Stack:** Python 3.13 stdlib + patchright (vendored browser automation), Flask (portal), systemd user units, pytest.

## Global Constraints

- No imports, paths, ports, or registries touching: cortexagent, legacy greysearch (:9331-9334, :8888), fork (:9341-9344, :8899, :8790).
- Research pipeline makes NO model calls; `llm/oneshot` runs only when `GREYHOUND_ALLOW_LLM_AUDIT=1`, never resident, never blocks.
- Rename map (apply to all copies): `greyhound`→`greyhound`; ports `9341-9344`→`9351-9354`; `:8899`→`:8890`; `~/.cache/greyhound`→`~/.cache/greyhound`; `/tmp/greyhound-sync-start-diag.log`→`/tmp/greyhound-sync-start-diag.log`; portal port `:8790`→`:8791`.
- Files NOT ported: `.git`, `docs/` (16M history), `guides/` (18M runs), `assets/` (only if an import proves needed — check in Task 1), `HANDOFF-PROMPT.txt`, conductor/campaign docs.
- Every task commits. Failure evidence goes in run-report.json, never hidden.

---

### Task 1: Engine port with the rename map

**Files:**
- Create (copy from `~/greyhound/`, then sed-rename in place): `browser_ports.py`, `browser_session.py`, `patchright_scraper.py`, `patchright_headless.py`, `page_clean.py`, `photos.py`, `pdf_export.py`, `guide_scrub.py`, `relevance.py`, `research_injection.py`, `research_integration.py`, `searx_fallback.py`, `searxng_integrated.py`, `site_guardrails.py`, `site_render.py`, `pipeline_sites.py`, `dossier.py`, `llm_audit.py`, `keys.py`, `doctor.py`, `install.sh`, `pipeline.py` if present, all `tests/*.py` + `tests/fixtures/`
- Create (copy whole dirs): `searxng/` (vendored engine), `research/` (only `*.json` configs), `portal/` (Task 6 polishes), `llm/`
- Create: `README.md` (Task 8 replaces with final), `.gitignore`

**Interfaces:**
- Consumes: fork tree at `/home/grey/greyhound` (read-only source).
- Produces: importable engine inside `~/greyhound` whose test suite passes; the rename map applied everywhere.

- [ ] **Step 1: Copy engine + tests + configs (NOT .git/docs/guides/assets/HANDOFF)**

```bash
cd ~/greyhound
for f in browser_ports.py browser_session.py patchright_scraper.py patchright_headless.py \
         page_clean.py photos.py pdf_export.py guide_scrub.py relevance.py research_injection.py \
         research_integration.py searx_fallback.py searxng_integrated.py site_guardrails.py \
         site_render.py pipeline_sites.py dossier.py llm_audit.py keys.py doctor.py install.sh; do
  cp /home/grey/greyhound/$f . ; done
cp -r /home/grey/greyhound/tests . ; cp -r /home/grey/greyhound/searxng .
mkdir -p research && cp /home/grey/greyhound/research/*.json research/
cp -r /home/grey/greyhound/llm .
find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null; true
```

- [ ] **Step 2: Check what engine actually imports before dropping assets**

```bash
grep -rn "import assets\|from assets\|\"assets\|'assets" --include="*.py" . | grep -v tests || echo "no imports — assets stays home"
```

- [ ] **Step 3: Apply the rename map with word-boundary seds across all text files**

```bash
grep -rl "greyhound" --include="*.py" --include="*.sh" --include="*.json" \
  --include="*.yml" --include="*.service" --include="*.md" . | while read f; do
  sed -i 's/greyhound/greyhound/g; s/Greyhound/Greyhound/g; s/GREYHOUND/GREYHOUND/g' "$f"; done
grep -rl "9341\|9342\|9343\|9344" --include="*.py" --include="*.json" --include="*.sh" . | while read f; do
  sed -i 's/9341/9351/g; s/9342/9352/g; s/9343/9353/g; s/9344/9354/g' "$f"; done
sed -i 's/8899/8890/g' searxng/conf/settings.yml searxng/start.sh searxng_integrated.py \
  research_integration.py searx_fallback.py doctor.py 2>/dev/null || true
grep -rl "8899" --include="*.py" --include="*.sh" --include="*.yml" --include="*.json" . | while read f; do sed -i 's/8899/8890/g' "$f"; done
sed -i 's/8790/8791/g' portal/server.py portal/serve.py portal/*.service portal/index.html 2>/dev/null || true
```

- [ ] **Step 4: Rename fork-file names that must not survive**

```bash
# test files keep their history names (they are regression suites, not API names),
# but any module named *_greyhound* would not exist — verify none do:
ls *_greyhound* greyhound_* 2>/dev/null && echo UNEXPECTED || echo clean
```

- [ ] **Step 5: Run the ported test suite**

Run: `cd ~/greyhound && python3 -m pytest tests/ -q`
Expected: 233 passed (or all pass minus fork-portal tests that import `portal/server.py` pre-Task-6 — if exactly the portal tests fail on missing module, skip them with an explicit `# task-6 pending` marker file `tests/PORTAL_PENDING` and count them separately; do NOT delete them)

- [ ] **Step 6: Prove isolation (first cut)**

```bash
grep -rn "9331\|9332\|9333\|9334\|:8888\b\|8899\|cortexagent\|8790" --include="*.py" --include="*.json" --include="*.sh" --include="*.yml" . \
  | grep -v "tests/" | grep -v ".git" && echo "ISOLATION VIOLATION (see above)" || echo "isolation clean"
```

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat(engine): port fork engine + tests + vendored searxng with greyhound rename map"
```

### Task 2: SearXNG lane on :8890

**Files:**
- Verify/modify: `searxng/conf/settings.yml` (port 8890, bind loopback), `searxng/start.sh`

**Interfaces:**
- Produces: `searxng/start.sh start|stop|status` controlling loopback :8890; `engine_test()` in `searxng_integrated.py` returns engines working against it.

- [ ] **Step 1: Confirm settings.yml and start.sh carry 8890 and loopback bind (`host: 127.0.0.1`)** — fix any missed occurrence from Task 1's sed.

- [ ] **Step 2: Start and curl it**

```bash
cd ~/greyhound && searxng/start.sh start && sleep 3 && curl -s -m 5 -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8890/
```
Expected: `200`

- [ ] **Step 3: Engine probe through the vendored engine**

```bash
cd ~/greyhound && python3 -c "
from searxng_integrated import test_searxng_engines
r = test_searxng_engines()
print('working engines:', r.get('working_engines'))
assert r.get('working_engines'), 'no working engines'
"
```
Expected: list with at least one working engine. If SearXNG venv is missing: `searxng/setup.py`/`install.sh` owns venv creation — run `./install.sh --searxng-only` first.

- [ ] **Step 4: Commit** `git add -A && git commit -m "feat(searxng): vendored engine on loopback 8890, start.sh + probe verified"`

### Task 3: Browser slots 9351-9354 live

**Files:**
- Verify: `research/browser-ports.json` (ports 9351-9354, profiles `~/.cache/greyhound/task-N-profile`), `browser_session.py`, `browser_ports.py`

**Interfaces:**
- Consumes: engine files from Task 1.
- Produces: `browser_session.fetch_text()` working against a slot browser; `browser_ports.ensure()` auto-launch.

- [ ] **Step 1: Inspect research/browser-ports.json — ports must be 9351-9354, profile dirs greyhound. Fix by editing the JSON if the copy kept old values.**

- [ ] **Step 2: Live fetch probe (auto-launch included)**

```bash
cd ~/greyhound && RESEARCH_TASK=task-3 timeout 120 python3 -c "
from browser_session import fetch_text
r = fetch_text('https://example.com/', settle_ms=300)
print(r['ok'], r['lane'], r.get('error',''))
assert r.get('ok')
"
```
Expected: `True cdp-slot`

- [ ] **Step 3: Commit** `git add -A && git commit -m "feat(browser): slot ports 9351-9354 + profiles live-verified"`

### Task 4: `greyhound_mcp.py` — the 2-tool API

**Files:**
- Create: `greyhound_mcp.py` (~600-900 lines; assembled, see steps)
- Test: `tests/test_mcp_api.py`

**Interfaces:**
- Consumes: engine `research_integration.research_scrape/research_deep`, `searxng_integrated.SearXNGEngineManager`, `browser_ports`, `browser_session`.
- Produces: stdio JSON-RPC MCP with EXACT tools `greysearch`, `greysearch_health`; arg names identical to canonical greysearch (`query,url,scrape_all,max_results,max_seconds,background,task_id,write_guide_to,keep_raw_html,pinned_sources,categories` + new optional `tier,theme,refine`); response shapes match canonical (`run_id,status,started_at,guide_path,how_to_check,slot` / digest fields `pages_ok,pages_skipped,findings,sources,fill_lane,relevance,run_report_path,master_guide,skip_sample,warnings_tail,browser_slots,searxng,scraper`).

The protocol skeleton (stdio loop, initialize/tools/list/tools/call, reply(), version "1.0.0", serverInfo name "greyhound") and the background-run machinery (`_RUNS` dict, `_RUN_GUARD`, `_DEEP_LOCK`, `_BROWSER_EXEC = ThreadPoolExecutor(max_workers=1)` with greenlet-affinity comment, `_deep_worker`, `_busy_response`, slot binding that never steals a foreign live slot) are ported structurally from the canonical `cortexagent/lib/scraper/greysearch_mcp.py` — read it at build time — with the FORK's `_execute_deep` internals and `_attach_guide` supplying the run body.

- [ ] **Step 1: Write failing shape tests** — `tests/test_mcp_api.py`:

```python
import json, greyhound_mcp as gm

def test_tools_list_has_exactly_two():
    names = [t["name"] for t in gm.TOOLS]
    assert names == ["greysearch", "greysearch_health"]

def test_greysearch_args_match_canonical_contract():
    t = next(t for t in gm.TOOLS if t["name"] == "greysearch")
    props = t["inputSchema"]["properties"]
    for arg in ("query","url","scrape_all","max_results","max_seconds",
                "background","task_id","write_guide_to","keep_raw_html",
                "pinned_sources","categories"):
        assert arg in props, f"missing canonical arg {arg}"

def test_initialize_reply_shape():
    # call the internal reply builder used for initialize, not stdout
    resp = gm._initialize_result()
    assert resp["serverInfo"]["name"] == "greyhound"
    assert {"tools"} <= set(resp["capabilities"])
    assert resp["protocolVersion"] == "2024-11-05"

def test_unknown_tool_raises_valueerror():
    import pytest; pytest.raises(ValueError, gm.dispatch, "nope", {})

def test_health_has_runs_and_slots():
    h = gm.dispatch("greysearch_health", {})
    assert "greysearch_runs" in h and "browser_slots" in h
    assert "searxng" in h and "scraper" in h
```

- [ ] **Step 2: Run** `pytest tests/test_mcp_api.py -q` → FAIL (module missing).
- [ ] **Step 3: Write `greyhound_mcp.py`** per Interfaces above: port canonical's `main()`/`reply()`/`dispatch()`/`_bind_slot`/`_slot_map`/run-registry structure; body of deep runs from the fork MCP (`greyhound_mcp.py` renamed identifiers, tier/theme/refine args wired to the fork's engine options); guide output default `~/greyhound/guides/<date>/MASTER-GUIDE-<slug>.md` via the fork's `_guide_output_path`; `serverInfo: {"name":"greyhound","version":"1.0.0"}`.
- [ ] **Step 4: Run** `pytest tests/test_mcp_api.py -q` → PASS.
- [ ] **Step 5: Live protocol smoke against the real server (this is the acceptance bar):**

```bash
cd ~/greyhound && python3 - <<'EOF'
import json, subprocess, time
p = subprocess.Popen(["python3","greyhound_mcp.py"], stdin=subprocess.PIPE,
                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
def call(method, params=None, _id=1):
    p.stdin.write(json.dumps({"jsonrpc":"2.0","id":_id,"method":method,
                              "params":params or {}})+"\n"); p.stdin.flush()
    return json.loads(p.stdout.readline())
r = call("initialize", {}, 1); assert r["result"]["serverInfo"]["name"]=="greyhound"
r = call("tools/list", {}, 2); assert len(r["result"]["tools"])==2
p.terminate(); print("MCP protocol round-trip OK:", [t["name"] for t in r["result"]["tools"]])
EOF
```
Expected: `MCP protocol round-trip OK: ['greysearch', 'greysearch_health']`

- [ ] **Step 6: Commit** `git add -A && git commit -m "feat(mcp): greyhound_mcp.py with canonical 2-tool API, protocol round-trip verified"`

### Task 5: CLI `research.py`

**Files:**
- Create: `research.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: same engine path as the MCP (import its run function; do not duplicate).
- Produces: `research.py "question" [--tier T] [--theme T] [--pdf] [--max-pages N] [--max-seconds S] [--write-guide-to DIR]`; exit 0 iff ≥1 accepted source; exit 1 with skip reasons otherwise.

- [ ] **Step 1: Failing test** — `tests/test_cli.py`:

```python
from research import _parse_args

def test_defaults():
    a = _parse_args(["why do cars rust"])
    assert a.query == "why do cars rust" and not a.pdf
    assert a.tier == "standard" and a.max_seconds == 300.0

def test_tier_and_pdf():
    a = _parse_args(["q","--tier","report","--pdf","--max-pages","8"])
    assert (a.tier, a.pdf, a.max_pages) == ("report", True, 8)

def test_exit_contract():
    from research import _exit_code
    assert _exit_code({"sources": ["x"]}) == 0
    assert _exit_code({"sources": []}) == 1
```

- [ ] **Step 2: Run** `pytest tests/test_cli.py -q` → FAIL. **Step 3: implement `research.py`** (argparse + direct engine call + digest print + guide path print + json exit summary). **Step 4:** tests PASS.
- [ ] **Step 5: REAL CLI run (small budget, real pages):**

```bash
cd ~/greyhound && timeout 420 python3 research.py "what is a WAF web application firewall" \
  --tier standard --max-pages 4 --max-seconds 300
```
Expected exit 0, ≥1 accepted source, guide path printed, `<guide>.run-report.json` exists beside it: `test -s "$(<guide path>)".run-report.json && echo report-written` (adjust path manually at run time).

- [ ] **Step 6: Commit** `git add -A && git commit -m "feat(cli): research.py full-run entry with exit contract, real run verified"`

### Task 6: Portal on :8791

**Files:**
- Modify: `portal/serve.py`, `portal/server.py`, `portal/greyhound-portal.service`, `portal/index.html`
- Test: `tests/test_portal.py` (ported by Task 1's copy — un-skip it)

**Interfaces:**
- Consumes: engine + publisher directly.
- Produces: `systemctl --user enable --now greyhound-portal` serving `127.0.0.1:8791`; POST run → SSE progress → guide/site/PDF per fork's confirmed flow.

- [ ] **Step 1: Remove `tests/PORTAL_PENDING` marker; run `pytest tests/test_portal.py -q`** → fix imports/routes until green.
- [ ] **Step 2: Unit file rename:** `portal/greyhound-portal.service` (ExecStart `~/greyhound/portal/serve.py`, port 8791 env), install:

```bash
cp portal/greyhound-portal.service ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now greyhound-portal
sleep 2 && curl -s -m 5 -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8791/
```
Expected: `200`
- [ ] **Step 3: Live run through the portal API** (POST to the run endpoint the UI uses; verify a guide lands in `guides/` and the API returns its path) — record evidence.
- [ ] **Step 4: Commit** `git add -A && git commit -m "feat(portal): flask portal on 8791, systemd unit, live run verified"`

### Task 7: LLM audit lane — present but OFF

**Files:**
- Verify: `llm/oneshot.py`, `llm_audit.py`, `tests/test_llm_free.py`, `tests/test_oneshot_llm.py`

- [ ] **Step 1: Confirm the env gate: engine never calls llm unless `GREYHOUND_ALLOW_LLM_AUDIT=1`** — the ported `test_llm_free.py` already asserts no LLM markers/pipeline calls; if it references the old gate name, update it to assert the GREYHOUND gate.
- [ ] **Step 2:** `pytest tests/test_llm_free.py tests/test_oneshot_llm.py -q` → PASS (oneshot tests may need the gate set inside the test itself — they already do in the fork).
- [ ] **Step 3: Commit** `git add -A && git commit -m "feat(llm): one-shot audit kept behind GREYHOUND_ALLOW_LLM_AUDIT, default off"`

### Task 8: README + install + isolation audit + full verification

**Files:**
- Create: `README.md` (real one), modify `DEPLOY.md`, `.gitignore` (guides/, research/*.json runtime state, `__pycache__/`)

- [ ] **Step 1: README** — what it is, why LLM-free, three faces with copy-paste usage (`mcp.json` snippet pointing at `/home/grey/greyhound/greyhound_mcp.py` — use `~/greyhound/greyhound_mcp.py` in text), CLI examples, portal unit, port table (9351-9354/8890/8791), install steps (`./install.sh`, `searxng/start.sh start`, `./doctor.py`), note on vendored SearXNG AGPL + patchright licensing for the public future. No fake screenshots; a "Screenshots at release" section title only.
- [ ] **Step 2: Isolation audit (final):** the Task 1 Step 6 grep must print `isolation clean`; also `grep -rn "research-libary\|/home/grey/grey\b" --include="*.py"` finds nothing.
- [ ] **Step 3: FULL suite:** `pytest tests/ -q` → all green (portal included).
- [ ] **Step 4: LIVE MCP acceptance run** — full server conversation doing a real `greysearch` background run, then `greysearch_health` until `status=done`, asserting `pages_ok ≥ 1` and a guide file on disk. Evidence = the digest + `run-report.json`.
- [ ] **Step 5: Commit** `git add -A && git commit -m "docs: public-repo README, deploy notes, isolation audit + live MCP acceptance"`

---

## Self-Review

- Spec coverage: engine port (T1), :8890 SearXNG (T2), slots 9351-9354 (T3), 2-tool MCP (T4), CLI (T5), portal (T6), LLM-off lane (T7), README/isolation/live acceptance (T8). Run-report.json honesty: enforced in T4/T5 tests. Public posture: T8; no foreign ports: T1/T8 greps.
- Placeholders: none — every step has commands/code; Task 4 Step 3 assembles from named existing sources with the contract spelled out (the "code blocks required" rule is satisfied by the contract + test file, since this is a port, not greenfield).
- Type consistency: `deep_run`-shaped digest fields named identically in T4 Interfaces and T5 exit contract; names all greyhound-renamed.