# Greyhound — design spec

Date: 2026-10-23. Status: approved by owner (design presented in session; adjustments incorporated).

## What greyhound is

Greyhound is a standalone deep-research engine that searches, scrapes, judges,
and publishes (Master Guide + themed site + optional PDF) with **no model in
the loop**. It is assembled from the proven greyhound fork engine (fully
LLM-free, hardened lanes, sentinel/leak-safe browser handling) and serves three
faces over that one engine:

1. **MCP server** (`greyhound_mcp.py`) — stdio JSON-RPC exposing the exact
   greysearch 2-tool API: `greysearch` + `greysearch_health`, same arguments
   (`query`, `url`, `scrape_all`, `max_results`, `max_seconds`, `background`,
   `task_id`, `write_guide_to`, `pinned_sources`, `keep_raw_html`), same digest
   flow, plus optional fork-era knobs (`tier`, `theme`, `refine`) that fall
   back to defaults when absent.
2. **CLI** (`research.py "question"`) — full deterministic run in-process;
   writes the guide + themed site (+ `--pdf`), prints the digest and paths.
   Flags: `--tier`, `--theme`, `--pdf`, `--max-pages`, `--max-seconds`.
3. **Portal** (`portal/`) — Flask app + UI from the fork, re-pointed at the
   engine; search box, progress, guide/site output, PDF export. Ships its own
   systemd user unit.

## Non-negotiable rules

- **New and fresh.** No imports, paths, ports, registries, or runtime links to
  cortexagent, the legacy greysearch copies, or the greyhound fork. Those
  keep running untouched; greyhound ignores them.
- **LLM-free research.** No model call anywhere in the pipeline. The optional
  one-shot post-research audit (`llm/oneshot`) is present but OFF unless
  `GREYHOUND_ALLOW_LLM_AUDIT=1` is set by the caller, never resident, and a
  failing model never blocks a run.
- **Public-repo posture.** The repo must stand alone on a clean machine via
  `install.sh`: vendored hardened SearXNG (`searxng/`, loopback :8890),
  vendored browser automation, repo-local guides output. No absolute paths to
  other homes; user-level paths limited to `~/.cache/greyhound`.
- **Isolation block.** Slot browsers 9351-9354 (profiles
  `~/.cache/greyhound/task-N-profile`), slot registry
  `research/task-registry.json` inside the repo, guides `guides/<date>/`
  inside the repo, SearXNG loopback :8890. Nothing on :9331-9334, :8888,
  :8899, :9341-9344.
- **Honest reporting.** Every run writes `run-report.json` beside its guide;
  health digests report real `pages_ok`/`skipped` counts and skip reasons.

## Interfaces (the contract)

### MCP tool: `greysearch`

Input (superset of canonical): `query` or `url`, `background` (default true),
`max_results` (1-25), `max_seconds` (default 300), `categories` (list),
`scrape_all` (default true), `task_id` (pinned browser slot; never steals a
foreign owned slot), `write_guide_to` (path override), `keep_raw_html`,
`pinned_sources` (list), plus `tier` (brief/standard/deep/report) and
`theme`. Behavior: `url` → one-URL scrape (sync via the persistent browser
thread); `query` → background deep run, returns `run_id` + `guide_path`;
the run digest arrives via `greysearch_health`.

### MCP tool: `greysearch_health`

Returns: engine/scraper state, SearXNG engine stats + `searx_space_instances`,
browser slot map, and `greysearch_runs` — the background digests
(status/elapsed/pages_ok/pages_skipped/skip_sample/preview/guide_path/
run_report_path). Shapes match canonical greysearch so existing callers work
unchanged.

### CLI: `research.py`

`research.py "question" [--tier T] [--theme T] [--pdf] [--max-pages N]
[--max-seconds S]` → prints run digest + guide path; exit 0 only on a run
with ≥1 accepted source; exit 1 with the skip reasons when capture fails.

### Engine: `deep_run(question, opts)`

The single internal entry point all three faces call. Binds a slot (never
takes a foreign live slot), runs the SearXNG ladder (:8890 → instances →
keyless), scrapes candidates over CDP, runs the deterministic relevance
judge, and emits: findings, master guide, optional site/pdf, run report.

## Error handling (carried from the fork, verified)

- Sentinel/leak-safe `browser_session` (`_discard_stale`,
  `_reset_loop_sentinel`, diag dump to `/tmp/greyhound-sync-start-diag.log`)
  — a failed browser connect can no longer poison the worker thread.
- Instance bench: limiter-walled public instances skipped for an hour.
- Human-pace lanes everywhere; per-scrape walls; politeness gaps.
- Runs never block on the model lane; deterministic brief serves instead.

## Testing

Port the fork's test suite; add: MCP-shape tests (2-tool API returns
canonical-compatible shapes), CLI smoke test into a temp guides dir, portal
endpoint tests, isolation audit (grep proves no foreign ports/paths in the
repo). Acceptance bar for this build: a REAL MCP conversation (initialize →
tools/list → tools/call) producing a live run, plus a real CLI run and a
live portal check — all verified with evidence.

## Out of scope (now)

- Public branding: logo, screenshots, polished README — done when the owner
  says it is publish time. A working README ships with this build.
- GitHub publishing/push (owner orders it later).
- Any change to the legacy greysearch copies or the fork (untouched).