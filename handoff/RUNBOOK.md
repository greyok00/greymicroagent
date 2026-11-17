# RUNBOOK — local-model audit of the research library (greylocalrag fork)

This kit lets a small LOCAL model (2B–3.5B class) work through the research
library indefinitely with no cloud dependency. The Python script owns order,
guards, and machine checks; the model only writes content via one JSON action
per turn. The model is NOT asked to follow free-form chat instructions — the
driver feeds it one protocol turn at a time, which is the only way a small
model reliably works.

The library is LOCAL FILES at `~/grey/research-libary` (your home is
`/home/grey`; the project directory inside it is named `grey` — the same one
folder, never a nested copy). There is NO website, NO scraper, and no
external organization involved. "NSCE" in this kit means nation State /
Crime Economy — the hidden fifth-group dimension (two required sections per
page), never an organization or domain.

## FORBIDDEN

Do not use, scrape, visit, cite, or mention any organization/website that an
earlier version of this kit invented by expanding "NSCE" into "National
Science and Engineering Center" with a ".gov" domain. It does not exist in
this project. We are not that website and have no affiliation with it or
anything related to it or its names.

## One-time setup

1. Confirm a local model is served by the shared ollama on :11600
   (this box: `huihui_ai/qwen3.5-abliterated:2b`).
2. Confirm the local SearXNG is up (the script's search backend):
   `curl -s "http://127.0.0.1:8890/search?q=test&format=json" | head -c 100`

## Run it

```bash
cd ~/grey/research-libary
python3 ~/greylocalrag/handoff/library-agent.py --dry-run          # preview queue + page facts
python3 ~/greylocalrag/handoff/library-agent.py                    # full autonomous walk
python3 ~/greylocalrag/handoff/library-agent.py --model huihui_ai/qwen3.5-abliterated:2b --max-pages 5
python3 ~/greylocalrag/handoff/library-agent.py --page legal/civil-procedure/fed-rule.html
```

The driver always works on the real library (`~/grey/research-libary`) no
matter where it is launched from. OLLAMA_HOST defaults to `127.0.0.1:11600`;
override with an env var if needed. The script auto-detects the first
non-cloud ollama model and walks every page in owner-mandated reverse order
(legal → finance → osint-pi → cybersecurity, backwards within each group).

## Resumability / safety

- All progress lives in `~/grey/research-libary/handoff/state.json`. Crash,
  Ctrl-C, or reboot — just rerun the command; finished pages are skipped,
  partial pages resume.
- Every edit writes a `.html.bak` beside the page first. Edits are
  append-only (inserted before the page-nav block) or exact-unique-match
  removals — the model can never rewrite or delete the page shell.
- Machine gate before any page is marked done: nation-state and
  crime-economy sections present, enough content, images/sources present, no
  foreign scripts, no broken breadcrumb links, no duplicate images.
- Append-only journal: `handoff/ledger.md`; full findings listed per page in
  `state.json`. No git commits are made by the kit (owner rule).

## Standing-owner-orders map

The owner command manifest (OWNER-COMMANDS.md) maps to the kit as follows:
reverse walk order → queue builder; NSCE (nation-state + crime-economy)
requirement + standard → AGENT-PROMPT.md "pages must have" + completion gate;
no dummy data / fact-check → prompt rules 2 and 3 + guard rejecting
example.com; foreign content → deterministic script scan + `remove_html`;
layout/text-wall concerns → prompt's paragraph/table discipline;
resumable/recoverable → state.json + .bak. The consolidated NSCE extra-pass
phase and final verification audit remain HUMAN-ORCHESTRATED phases on top
of this loop — after the walk completes, rerun the kit with the NSCE page
list from OWNER-COMMANDS.md item 11 (#95–99, #84–80, #64–60, #33–39).
