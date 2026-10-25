# Full greyagent audit — 2026-10-24 (integration + tools)

Scope: every compiled surface (core/*.so, core/greyhound/*.so, tools/*.so,
tools/*/*.so, services/*.so, mcp/*.so), the JS TUI harness dist, and the
MCP registry. Greyhound rebuilt/audited elsewhere (separate session).

## Integration (task: greyhound → core)
- core/greyhound/: 25 .so (byte-identical to the pinned mcp twins) + data dirs
  (data/, research/, assets/, docs/).
- Integrity chain: loader verifies greyhound_mcp .so vs FROZEN MANIFEST before
  every spawn; spawn sets GREYAGENT_CORE_TOOLS=core/greyhound and run_server.py
  inserts that path AFTER mcp so the verified bytes are the bytes that run
  (fixed: PYTHONPATH lost to sys.path.insert; fixed: insert-order shadowing).
- Stdio smoke through the loader's invocation: initialize + tools/list give
  greyhound + greyhound_health. Loader registers them as native tools.

## Findings fixed this audit
1. core/greyhound/docs (greyhound build plans/specs) contained cortexagent
   references → removed from the shipped package.
2. core/greyhound/research/browser-ports.json cortexagent strings → remapped
   (twin in mcp/ remapped identically).
3. Stale model/wiring.py + model/setup.py (source twins of compiled .so) →
   deleted; zero .py in core/tools/services/model now (greyhound kit-source
   assets excepted — they are site-kit payload data, not exec paths).

## Verification
- build/src/audit.py core tools services mcp model → CLEAN (4 functional
  filter strings documented).
- strings sweep ALL compiled .so: 0 http(s):// URLs, 0 telemetry SDKs,
  0 cortexagent/anthropic/claude/anthropic strings, 0 paths outside
  /home/grey/greyagent.
- TUI dist: 0 vendor endpoints; telemetry.js = OTel span wrappers, no
  exporter, no outbound; loads clean under node.
- Registry: greyhound_mcp hash OK (enabled), memory + research hash OK
  (DISABLED, prepped only — enable is a later owner decision).
- MANIFEST 1562 files (45 core/greyhound pins incl. data), 0 failures.
- tests/verify_compiled.py PASS; pytest 29 passed.
- Known remaining, deliberate: vendored node_modules READMEs still flagged by
  the audit engine's known-vendor scan (doc text, unused paths); TUI minify of
  JS dist is a separate follow-up if ever ordered.
Verdict: greyagent core + shipped tools AUDIT CLEAN.