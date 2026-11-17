# greylocalrag — product design spec (2026-11-17)

A universal, self-contained, RAG-first local AI agent for machines without
dedicated GPUs. Public release. Non-power-user audience. Built specifically
for retrieval-grounded answers.

## 1. What this product is

greylocalrag is a local AI agent whose answers come from a knowledge base the
user builds and controls, not from the model's memory. Every turn passes
through a deterministic retrieval gate before the model sees it. When local
knowledge answers the question, the answer cites it. When it does not, the
agent searches the web once (greysearch), offers to store what it found, and
asks consent before storing anything. When neither source exists, the agent
says so instead of inventing an answer.

Target devices: CPU-only machines (8-16 GB RAM, no dGPU), example device class:
a Surface tablet. Windows is the primary host target and gets a real
installer; Linux ships as a co-equal second artifact (.deb). The agent runs
its own model server, its own retrieval
engine, and its own search lane entirely on the user's machine. No cloud
model, no external model dependency, nothing shared with other software on
the host.

## 2. HARD constraints (owner directives, non-negotiable)

1. **Model is FIXED:** `huihui_ai/qwen3-vl-abliterated:2b` served by the
   vendored `greylocalrag-server` (llama.cpp b3fa6995). No model swap, no size
   change, no automatic hardware adaptation — now or later. Owner 2026-11-17:
   "no changes no matter what... don't change the model size or anything yet."
2. **Temperature band 0.0-0.2**, clamped by the gate on every request; baked
   default 0.1 (launcher GREYAGENT_TEMP and param-less server default, both
   already set 2026-11-16).
3. **Ports 7640-7647 are fork-unique**, verified free against every claimed
   range and live listener; below the Linux ephemeral range. Nothing else may
   bind them. Sessions never fight foreign listeners.
4. **Never auto-ingest.** Web content enters the KB only after an explicit
   user yes. Removal is always available and always easy.
5. **No personal data ships.** The release tree contains nothing owner-specific
   (no sessions, no personal corpora, no host-locked state).
6. **Off-limits ports** (:11434 dead forever, :11435-11436, :11598-11599,
   :11600) are never touched, listened on, or proxied by this fork.
7. Cleanup kills only pids this session captured. No name-pattern sweeps.
8. Publish gate: nothing is pushed or released without explicit owner OK.

## 3. Architecture

One session occupies three ports inside the unique block:

    TUI  ->  RAG gate :7641  ->  slimtoken :7642  ->  model server :7640

- **Model server** `:7640` — vendored llama.cpp (`vendor/greylocalrag-server/`,
  renamed from greymini-server so the binary name is fork-unique), serving
  `~/.greylocalrag/models/qwen3-vl-2b-abliterated.gguf` (weights are a symlink
  to the immutable ollama-store blob during development; a release fetches the
  gguf with a pinned checksum instead). CPU-only mode by default (NGL 0 when a
  GPU is present-but-held is still available via the existing VRAM interlock),
  context ladder 64k with 32k floor, thinking off, sampling pinned 0.1.
- **slimtoken** `:7642` — existing vendored request-filter lane; distills
  oversized tool results before the model sees them. Unchanged behavior.
- **RAG gate** `:7641` — the only new moving part. A small loopback-only
  service the TUI talks to. For EVERY request it: (a) builds the retrieval
  query deterministically from the user's latest turn (prompt text, trimmed --
  no model involved); (b) searches the local KB (semantic + keyword, the
  fork's own vendored retrieval engine); (c) injects the top chunks above the
  quality floor into the context as `[KB:<db>#<id> score=<s>]` blocks; (d)
  rewrites the request toward slimtoken with `temperature` clamped into the
  0.0-0.2 band; (e) when nothing above the floor exists, prepends
  `[NO-KB-GROUNDING]` instead of chunks. The gate stores nothing — no prompt
  logging, no journaling. It serves only this fork.
- **The card** (`model/greylocalrag.md`) carries the grounding law: answer
  only from `[KB:]` blocks; with `[NO-KB-GROUNDING]` present, never state
  document facts — run tools or ask to research instead.

Boot order is the existing launcher order (mask, frozen-tree gate, lane chain,
VRAM interlock, async model spawn, splash, TUI). The launcher's slot arrays
become triples: session 1 = 7640/7641/7642, session 2 = 7643/7644/7645,
7646-7647 spare-expansion (a third session later just widens the block).

### 3.2 Loop prevention and supervision (ported from the cortex-agent family)

greymini's own behavior audit showed the failure class this product must never
ship with: runaway loops ("WHY ARE YOU LOOPING"), instruction drift, empty
replies, polling wedges. The cortex-agent family already solved these with a
deterministic supervision harness (no judge LLM anywhere); greylocalrag vendors
that machinery as fork-owned code and ships it default-ON, so non-power users
get the polish without ever configuring it:

- **Loop-guard hold, diff-based — never indiscriminate (owner order 2026-11-17):**
  an identical re-issued tool call is HELD — neither executed nor refused —
  until the backing work's state actually changes (diff + staleness checks:
  file mtimes, output deltas, process liveness). The guards must never punish
  legitimate work: a FIRST execution is never blocked; a re-issue whose backing
  state HAS changed is released immediately; long-running processes that keep
  producing evidence of progress run to completion — the only cap is
  staleness-based (runs with ZERO state change cap at 300 s; duration itself
  is never the criterion); fast tools get only a short settle gap. This ports
  the proven cortex-agent loop-guard so genuine "wait for it to finish" loops
  survive while true no-progress repetition is caught.
- **Supervision core:** fork-owned port of the supervision core with the
  hardened rulebook defaults: repetition_limit 3, error_burst_min 4 in a
  6-event window, storm_min_turns 3, refusal_repeat_limit 3,
  length_storm_limit 3; detector threshold 3 identical events; escalation
  ladder steer -> force-alternative -> cancel -> respawn -> stop-and-surface,
  targeting at most 3 wasted model turns; the stats sidecar carries no
  authority over the agent. Events land in-steer and an event stream, never
  in hidden control channels.
- **Blocking health polls:** status/health polls of long-running work (greysearch
  runs, model loads) block until state changes (bounded wait + re-poll
  tunables, cortex-agent pattern) instead of tight-polling — the wedge class
  is closed at the mechanism level.
- The /rag surface exposes supervision STATUS in plain words ("held a repeat
  call — still waiting on the search", "recovered from a stuck run"), not knobs.

## 4. Knowledge base subsystem

- **Self-contained.** The retrieval engine is vendored into the fork tree
  (ported from the owner's private knowledge-ingestor: HTML/PDF extraction,
  heading-aware chunking, MiniLM embeddings, RRF band search, atomic writes,
  job journal with retry/resume). No runtime dependency on that private tree.
- **Storage** `~/.greylocalrag/dbs/` — plain db folders, format-compatible
  with the private system (pack.jsonl + vectors + ids + manifest), so
  offline search of any db also works with the standalone reader.
- **Seed database `commands`** — generic, license-clean reference of standard
  Linux and Windows 11 commands, built at release time. Sources (enumerated in
  the implementation plan): tldr-pages-derived cards (CC-BY with an
  attribution file) for breadth, plus our own-written command cards where
  third-party terms are murky (e.g. no verbatim Microsoft Learn copying).
  Every record carries source + license provenance.
- **Every record has provenance** (source path or URL, ingestion date, tool)
  so users can always see where stored knowledge came from.
- **Never personal.** Nothing owner-specific is seeded, referenced, or bundled.

## 5. Ingest is consent-gated; removal is first-class

After a greysearch deep run completes, the agent presents the digest and asks:
ingest this into your RAG? Yes stores the Master Guide section-by-section plus
cited pages, with provenance. No stores nothing — never partial. The agent
never silently swallows web content because searches can surface material the
user does not want kept.

Removal commands act per record, per source URL, or per database, with one
plain confirmation each. Removing shows what will be removed before removing
it. Users can list everything stored (`status`) at any time.

## 6. In-app control surface (non-power-user UX)

All adjustability lives inside the running application as slash commands
(wave-2 may add a visual panel; commands come first because they are small,
testable, and already match the TUI's extension mechanism):

    /rag status                     what the agent knows (dbs, counts, health)
    /rag ingest <path | url>        add a document or page now
    /rag remove <id | url-prefix>   remove stored records (confirms first)
    /rag temp <n>                   answer temperature (clamped to 0.0-0.2, default 0.1)
    /rag offline on|off             force KB-only mode (visible banner)

The mechanism is a TUI extension (verify the fork's extension compile flow in
the implementation plan); it must pass the frozen-tree gate like everything
else.

## 7. Search lane and offline behavior

- Public users get a fork-owned search surface against public SearXNG
  instances (keyless), pluggable so a hobbyist can point it at their own
  instance later. The private searxng/proxy stack is never referenced.
- Offline moments are visible, never silent: KB-only mode shows an explicit
  "offline — answering from your knowledge base only" banner, and unknown
  topics get the honest "no grounded material — go online to research?"
  answer instead of a guess.

## 8. Splash screen (product front door)

Full splash redesign, not a tweak: the launcher's splash module
(`build/src/splash.py`, whose compiled form the boot gate already flags for
rebuild) is replaced entirely. The splash is the first thing a non-power
user sees, so it must teach the product in five seconds.

ASCII logo in the fork's 8-bit greyscale style, byline, one short how-to
paragraph, and the ingestor commands printed on first launch:

    GREYLOCALRAG
    grounded answers from your own knowledge — RAG for CPU-only machines

    HOW TO USE
      Ask anything. Answers come from your KB with citations, temperature cold.
      No grounded material? The agent asks before it goes searching the web.
      What it finds stays out of your KB until you say yes.

    YOUR RAG
      /rag ingest <file | url>      teach it
      /rag remove <id | source>     make it forget
      /rag status                   what it knows
      /rag temp <n>                 answer temperature (0.0-0.2)

## 9. Boot, build, and the compile pass

Step 1 of implementation is the compile pass the frozen-tree gate already
demands: rebuild `mcp/src/memory` and `build/src/splash` .so modules (the
identity sweep made the sources newer than their binaries), regenerate
`state/MANIFEST.json`, and get `bin/verify_compiled.py` green before anything
else is layered on. New code (gate, KB subsystem, splash, extension) follows
the tree's own verified-compile conventions.

## 10. Testing

- Unit: gate temperature clamping (0.0-0.2, out-of-band clamped), chunk
  injection shape, quality-floor refusal behavior, no-logging guarantee.
- Grounding: seed-question answered from `commands` with citations; unknown
  topic produces `[NO-KB-GROUNDING]` + honest refusal (no invention).
- Consent flow e2e: research run completes, prompt appears, decline stores
  nothing, accept stores with provenance; remove then makes the records
  unfindable.
- Reuse the existing 9-gate capability bench on the fixed model.
- Loop/supervision gates: an identical re-issued tool call is HELD until
  backing state changes; diff-hold fairness — a FIRST run is never blocked,
  a re-issue whose backing state changed releases immediately, and a
  process with continuous state change survives far past 300 s (only
  zero-progress runs are capped); the 3-identical-events detector fires
  ladder step 1; health polls block rather than tight-poll (no wedge);
  supervision ships default-ON with no judge LLM anywhere.
- Boot gate green; deb portable build only after owner-reviewed plan.

## 11. Release wave (separate plan phase, publish-gated)

1. Scrub: fresh git history (single commit), no sessions/state/logs/deb
   artifacts, no host-locked paths in shipped configs, no personal data.
2. Apache-2 LICENSE, exactly one README (with splash screenshots), no
   comments / minified per the code-shipping default, no codename leakage.
3. Model distribution: companion gguf download with pinned checksums at
   install (weights are not re-shipped in the deb; licenses for the
   abliterated weights are verified before bundling is even considered).
4. Packaging, both artifacts (owner 2026-11-17: "windows is going to be the
   target here so an installer would be great but also linux source or .deb
   is also good so do both"):
   - Linux: .deb via the existing packaging script (buildable and testable
     on this machine immediately).
   - Windows (primary target): NSIS/Inno-style installer + portable zip.
     Requires a dedicated Windows build pass: Windows cython (.pyd) builds
     of the compiled modules (the tree ships Linux .so files that cannot
     run on Windows), a Windows build of the model server from the pinned
     llama.cpp commit (b3fa6995), a Windows bootstrap replacing the bash
     launcher, and the node TUI bundled as-is (it is portable). The Windows
     artifact is built and tested on Windows hardware or a VM — a Linux
     cross-compile is not trusted for this. Ports 7640-7647 policy carries
     over; the installer handles the Windows firewall first-run prompt.
5. Publish only when the owner says ready. Verify the artifact, not the log.

## 12. Non-goals

- No model swap or size change, ever, without a new owner directive.
- No automatic hardware-fitting ladder; settings are manual and in-app.
- No auto-ingest of web content, ever.
- No cloud model lane; no :11600/:11434 contact.
- No analytics, no telemetry.

## 13. Open items (resolve in the implementation plan)

- Exact seed-source list and license attribution files for `commands`.
- TUI extension compile flow verification for the slash-command surface.
- Vision path: the extracted gguf carries no separate projector blob, so
  image input via the own server is unverified — text-first by default;
  vision verified at boot if the weights include it.
- Windows build environment: access to Windows hardware or a VM for the
  Windows build pass (pyd modules, model server exe, installer testing).
