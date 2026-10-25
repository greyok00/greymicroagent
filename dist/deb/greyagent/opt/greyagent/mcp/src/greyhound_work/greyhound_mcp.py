from __future__ import annotations
import json
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutTimeout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
sys.path.insert(0, str(Path(__file__).parent))
_BANNED_SEARCH_MARKERS = ('chatgpt.com', 'api.openai.com', 'openai.azure.com', ':13200', 'g4f', 'tavily', 'serper', 'brave-search', 'brave_search', 'api.firecrawl.dev', 'firecrawl-mcp')

def _guard_search_lane() -> None:
    for var in ('FIRECRAWL_API_KEY', 'TAVILY_API_KEY', 'SERPER_API_KEY', 'BRAVE_API_KEY', 'OPENAI_API_KEY', 'GREYHOUND_URL', 'SEARXNG_URL'):
        val = (os.environ.get(var) or '').lower()
        if not val:
            continue
        for marker in _BANNED_SEARCH_MARKERS:
            if marker in val:
                raise RuntimeError(f'greyhound AUDIT GUARD: banned search endpoint in {var}={val!r} (marker {marker!r}). greyhound is the ONLY researcher; OpenAI/g4f/ChatGPT and paid lanes (Tavily/Serper/Brave/Firecrawl) are forbidden by the standing bans recorded in the memory dir.')
_guard_search_lane()
import research_integration as research_bridge
from research_integration import get_bridge, research_scrape, research_search, research_deep
from searxng_integrated import SearXNGEngineManager
try:
    import keys as research_keys
except Exception:
    research_keys = None
import pipeline_sites as pipeline
DEFAULT_MAX_RESULTS = 10
_LINKS_PER_PAGE_IN_RESPONSE = 150
_THIN_FILL_LIMIT = 5
_THIN_FILL_BUDGET_S = 90.0
_RUNS_KEEP = 25
_GUIDE_PREVIEW = 1600
_DEEP_LOCK = threading.Lock()
_RUN_GUARD = threading.Lock()
_RUNS: Dict[str, dict] = {}
_BROWSER_EXEC = ThreadPoolExecutor(max_workers=1, thread_name_prefix='greyhound-browser')

def _redacted(obj):
    if research_keys is None:
        return obj
    try:
        return json.loads(research_keys.redact(json.dumps(obj, default=str)))
    except Exception:
        return obj
_REMOVED = {'greyscrape': 'greyhound(url=..., keep_raw_html=...)', 'research_deep': 'greyhound(query=..., background=...)  [deep IS the default — do NOT call the removed name again]', 'research_search': 'greyhound(query=..., scrape_all=false)', 'research_scrape': 'greyhound(url=...)', 'research_sites': 'no tool — site tiers live in research/data/sites.json in this repo', 'research_task_registry': 'greyhound(query=...) — slot assignment is automatic; pass task_id only to pin a specific slot', 'greyhound_engines': 'greysearch_health()  [engine stats are in the searxng section]'}
TOOLS = [{'name': 'greyhound', 'description': "THE ONE WEB RESEARCHER. Default flow = deep search + scrape + Master Guide, fired like a background task: call it ONCE (background=true default) and it returns immediately with run_id and the guide path; greysearch_health then reports the finished digest (pages, findings, guide path, warned lanes); you read the guide file when done. Do not re-call greysearch with tweaked arguments while health shows a run active — that is the retry loop this design exists to kill. The search lane ladder is automatic inside one call: local SearXNG (:8890) first, then searx.space public instances, then direct keyless lanes. Long questions are decomposed into separate short keyword searches (one per entity; connective words stripped) — never long-tail queries. Full pages are scraped headless through patchright on the session's own browser slot (tables/headings/links/images/videos/code all captured, paragraph structure preserved). Thin runs auto-fill from public instances and report exactly what failed or was skipped — they never pretend to be complete. Provide url INSTEAD of query to scrape ONE known page synchronously and fast. scrape_all=false = ranked search results only (no scraping, no guide).", 'inputSchema': {'type': 'object', 'properties': {'query': {'type': 'string', 'description': 'Research question. Required unless url is given.'}, 'url': {'type': 'string', 'description': 'Scrape ONE page instead of researching (sync, fast; full payload with media/tables/code).'}, 'scrape_all': {'type': 'boolean', 'description': 'true (default) = full deep run with scraping + Master Guide; false = search-only, ranked sources'}, 'max_results': {'type': 'integer', 'description': 'Max pages scraped in a deep run (default 10, hard max 25)'}, 'categories': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Optional SearXNG categories (news/it/science/…; unknown ones are normalized to general)'}, 'write_guide_to': {'type': 'string', 'description': 'Override the Master Guide output path (.md file or dir)'}, 'keep_raw_html': {'type': 'boolean', 'description': 'Include raw page HTML in the response (default false)'}, 'max_seconds': {'type': 'number', 'description': 'Wall-clock budget for the whole deep run (default 300)'}, 'tier': {'type': 'string', 'enum': ['brief', 'standard', 'deep', 'report'], 'description': 'Run tier — brief 3/240s, standard 4/300s, deep 6/420s, report 8/540s (pages/seconds). Explicit max_results/max_seconds always win.'}, 'background': {'type': 'boolean', 'description': 'true (DEFAULT) = fire like a task: return run_id now, digest arrives via greysearch_health; false = synchronous full run in this call (blocks until finished)'}, 'task_id': {'type': 'string', 'description': "Optional 'task-1'..'task-4' (or '1'..'4'): pin a specific browser slot. Omitted = AUTO-ASSIGN a conflict-free slot: the shared registry is checked and a slot owned by another live session is never taken."}, 'pinned_sources': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Exact primary-domain URLs fetched FIRST (ranked ahead of search); each contributes its top same-site topical links to the pool. Use when general search drifts off-topic.'}}, 'required': []}}, {'name': 'greyhound_health', 'description': 'ONE status call for greyhound: SearXNG engine/lane stats, searx.space instances, browser-slot map (which session owns which port), AND the digest list for every background greyhound run (running / done / failed, pages, findings, guide path). Call this after a background greyhound to learn its outcome — do not poll in a tight loop, and do not re-call greyhound while a run is active.', 'inputSchema': {'type': 'object', 'properties': {}}}]

def _guide_output_path(query: str, slug_tag: str='') -> Path:
    slug = ''.join((ch if ch.isalnum() else '-' for ch in query.lower()))[:60].strip('-') or 'guide'
    if slug_tag:
        slug = f'{slug}-{slug_tag}'[:80]
    out = os.environ.get('GREYHOUND_OUT_DIR', '')
    if not out:
        pages_env = os.environ.get('RESEARCH_PAGES', '')
        if pages_env and Path(pages_env).is_dir():
            out = pages_env
    if out:
        b = Path(out)
        if b.suffix == '.md':
            b.parent.mkdir(parents=True, exist_ok=True)
            return b
        b.mkdir(parents=True, exist_ok=True)
        return b / f'MASTER-GUIDE-{slug}.md'
    day_dir = Path(__file__).resolve().parent / 'guides' / f'{datetime.now(timezone.utc):%Y-%m-%d}'
    return day_dir / f'MASTER-GUIDE-{slug}.md'

def _resolve_guide_path(spec, query: str, slug_tag: str='') -> Path:
    if not spec:
        return _guide_output_path(query, slug_tag)
    b = Path(str(spec))
    slug = ''.join((ch if ch.isalnum() else '-' for ch in query.lower()))[:60].strip('-') or 'guide'
    if slug_tag:
        slug = f'{slug}-{slug_tag}'[:80]
    if b.is_dir() or b.suffix != '.md':
        b.mkdir(parents=True, exist_ok=True)
        return b / f'MASTER-GUIDE-{slug}.md'
    b.parent.mkdir(parents=True, exist_ok=True)
    return b

def _thin_fill(query: str, result: dict) -> None:
    import page_clean as _page_clean
    import relevance as _relevance
    fill = {'triggered': True, 'searched': False, 'scraped': 0, 'urls': [], 'accepted': 0, 'quarantined': 0, 'rejected': 0, 'rejected_detail': [], 'errors': []}
    try:
        import searx_fallback as _sf
        lad = _sf.search(query, max_results=10)
        fill['searched'] = True
        if not (lad.get('ok') and lad.get('results')):
            fill['errors'].append(f"ladder search: {lad.get('source', 'no results')}")
        else:
            fill['ladder_source'] = lad.get('source')
            have = {p['url'] for p in result.get('pages_fetched', [])}
            fresh = [r for r in lad['results'] if r.get('url') not in have]
            bridge = get_bridge()
            deadline = time.time() + _THIN_FILL_BUDGET_S
            gated: list = []
            for r in fresh:
                dom = r.get('domain') or bridge._extract_domain(r.get('url', ''))
                pf = _relevance.prefilter(r.get('url', ''), title=r.get('title', ''), snippet=r.get('content', '') or r.get('snippet', ''), domain=dom, tier=r.get('tier') or bridge._get_tier(dom), question=query)
                if pf['decision'] == 'reject':
                    fill['rejected'] += 1
                    fill['rejected_detail'].append({'url': r.get('url', ''), 'reason': pf['reason']})
                    continue
                r = dict(r)
                r['prefilter'] = pf
                gated.append(r)
            fill['prefilter_kept'] = len(gated)
            candidates: list = []
            for r in gated[:_THIN_FILL_LIMIT]:
                if time.time() > deadline:
                    fill['errors'].append('fill scrape budget reached')
                    break
                sr = bridge.research_scrape(r['url'])
                if not sr.get('ok'):
                    fill['errors'].append(f"scrape {r['url'][:80]}: {str(sr.get('error'))[:120]}")
                    fill['rejected'] += 1
                    fill['rejected_detail'].append({'url': r['url'], 'reason': 'scrape failed'})
                    continue
                sr = dict(sr)
                sr['title'] = r.get('title') or sr.get('title', '')
                sr['tier'] = r.get('tier') or sr.get('tier', 'unlisted')
                cleaned = _page_clean.clean_page(sr)
                if _page_clean.is_thin(cleaned):
                    fill['rejected'] += 1
                    fill['rejected_detail'].append({'url': r['url'], 'reason': f"thin_content ({cleaned.get('main_chars', 0)} chars)"})
                    continue
                sr['clean'] = cleaned
                candidates.append(sr)
                fill['scraped'] += 1
            if candidates and _relevance.judge_available():
                decisions = _relevance.judge_pages(query, [research_bridge._judge_view(sr) for sr in candidates])
                for sr, d in zip(candidates, decisions):
                    sr['relevance'] = d
            elif candidates:
                for sr in candidates:
                    sr['relevance'] = {'decision': 'quarantine', 'relevance_score': 50, 'source_type': _relevance.classify_source_type(sr.get('domain', ''), sr.get('tier', ''), sr.get('title', '')), 'reason': 'judge_unavailable — quarantined, never auto-accepted', 'allowed_content': [], 'risk_flags': []}
            for sr in candidates:
                rel = sr.get('relevance') or {}
                if rel.get('decision') == 'accept':
                    result.setdefault('pages_fetched', []).append(sr)
                    result.setdefault('sources', []).append(sr['url'])
                    fill['urls'].append(sr['url'])
                    fill['accepted'] += 1
                elif rel.get('decision') == 'quarantine':
                    fill['quarantined'] += 1
                    fill['rejected_detail'].append({'url': sr['url'], 'decision': 'quarantine', 'reason': rel.get('reason', '')})
                else:
                    fill['rejected'] += 1
                    fill['rejected_detail'].append({'url': sr['url'], 'decision': 'reject', 'reason': rel.get('reason', '')})
            if fill['accepted'] == 0 and gated:
                fill['errors'].append('fill lane produced 0 accepted pages — thin run reported honestly, thresholds not lowered')
    except Exception as e:
        fill['errors'].append(f'{type(e).__name__}: {str(e)[:160]}')
    result['fill_lane'] = fill

def _shape_response(result: dict, keep_raw: bool) -> dict:
    shaped = {k: v for k, v in result.items() if k != 'pages_fetched'}
    pages = []
    for p in result.get('pages_fetched', []):
        sp = dict(p)
        if not keep_raw:
            sp.pop('raw_text', None)
        sp.pop('html', None)
        links = sp.get('links') or []
        if len(links) > _LINKS_PER_PAGE_IN_RESPONSE:
            sp['links'] = links[:_LINKS_PER_PAGE_IN_RESPONSE]
            sp['links_capped_at'] = _LINKS_PER_PAGE_IN_RESPONSE
        pages.append(sp)
    shaped['pages_fetched'] = pages
    warnings = list(shaped.get('warnings') or [])
    for p in pages:
        if p.get('html_capped'):
            warnings.append(f"html capped for {p.get('url')}")
        flags = p.get('injection_flags') or []
        if flags:
            warnings.append(f"{len(flags)} injection-pattern flag(s) on {p.get('url')}")
    shaped['warnings'] = warnings
    rr = result.get('run_report')
    if isinstance(rr, dict):
        shaped['relevance_summary'] = {'candidate_count': rr.get('candidate_count'), 'scraped_count': rr.get('scraped_count'), 'accepted_count': rr.get('accepted_count'), 'quarantined_count': rr.get('quarantined_count'), 'rejected_count': rr.get('rejected_count'), 'accepted_sources': rr.get('accepted_sources', [])[:50], 'quality_warnings': rr.get('quality_warnings', [])}
        shaped['skipped_pages_summary'] = {'count': len(rr.get('skipped_pages') or []), 'sample': (rr.get('skipped_pages') or [])[:20]}
    qp = result.get('quarantined_pages')
    if qp:
        shaped['quarantined_pages'] = qp[:50]
    return shaped

def _set_run(run_id: str, **fields) -> None:
    with _RUN_GUARD:
        d = _RUNS.setdefault(run_id, {})
        d.update(fields)
        if len(_RUNS) > _RUNS_KEEP:
            old = sorted(_RUNS, key=lambda k: _RUNS[k].get('started_ts', 0))[:-_RUNS_KEEP]
            for rid in old:
                _RUNS.pop(rid, None)

def _busy_response(what: str) -> dict:
    with _RUN_GUARD:
        running = {rid: {k: d.get(k) for k in ('query', 'started_at', 'status')} for rid, d in _RUNS.items() if d.get('status') == 'running'}
    return {'ok': False, 'busy': True, 'waiting_for': what, 'active_runs': running, 'note': "one deep run at a time (the private browser is reused per process). Ask greyhound_health for the active run's digest; do not re-call greyhound."}

def _execute_deep(query: str, categories: Optional[List[str]], max_results: int, budget: float, pinned=None) -> dict:
    result = research_deep(query, categories=categories, max_pages=max_results, max_total_seconds=budget, pinned_sources=list(pinned or []))
    if len(result.get('pages_fetched', [])) < 3:
        _thin_fill(query, result)
        fill = result.get('fill_lane') or {}
        result['ladder_lane'] = str(fill.get('ladder_source') or '') if isinstance(fill.get('ladder_source', ''), str) else ''
    return result
_CORPUS_GLOBS = (str(Path(__file__).resolve().parent / 'guides' / '**' / '*.md'),)

def _corpus_related(query: str, guide_path: Path, top: int=6) -> str:
    import glob as _g
    tokens = {t for t in re.split('[^a-z0-9]+', query.lower()) if len(t) > 3}
    if not tokens:
        return ''
    cands = []
    seen = set()
    for pat in _CORPUS_GLOBS:
        for f in _g.glob(pat):
            fp = str(f)
            if fp == str(guide_path) or fp in seen:
                continue
            seen.add(fp)
            try:
                st = os.stat(fp)
                if st.st_size < 800:
                    continue
                hay = Path(fp).name.lower()
                with open(fp, errors='ignore') as fh:
                    for ln in fh.readlines()[:25]:
                        if ln.startswith('#'):
                            hay += ' ' + ln.lstrip('# ').strip().lower()
                            break
                n = sum((1 for t in tokens if t in hay))
                if n:
                    cands.append((n, st.st_mtime, st.st_size, fp))
            except Exception:
                continue
    cands.sort(reverse=True)
    clean = []
    for n, mtime, size, fp in cands[:20]:
        try:
            with open(fp, errors='ignore') as fh:
                markers = fh.read().count('DATA NOT CAPTURED')
        except Exception:
            markers = 0
        if markers <= 8:
            clean.append((n, mtime, size, fp))
        if len(clean) >= top:
            break
    cands = clean
    if not cands:
        return ''
    lines = ['---', '', '## Related research in our corpus', "Machine-selected by filename/heading match with this run's question — links only; verify before trusting.", '']
    for n, mtime, size, fp in cands[:top]:
        ts = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d')
        lines.append(f'- `{Path(fp).name}` ({size:,} bytes, {ts}) — {fp}')
    text = '\n'.join(lines) + '\n'
    try:
        with open(guide_path, 'a', errors='ignore') as fh:
            fh.write('\n' + text)
        return text
    except Exception:
        return ''

def _attach_guide(result: dict, query: str, write_path: Path) -> dict:
    output_spec = None
    result['llm_audit'] = {'used': False, 'reason': 'not attempted'}
    try:
        from dossier import build_dossier
        doss = build_dossier(result, query)
        result['dossier'] = doss
        import llm_audit as _la
        if _la.audit_allowed() and _la.endpoint_ok():
            output_spec = _la.spec_for_compose(query, doss)
            if output_spec:
                result['llm_audit'] = {'used': True, 'model': output_spec.get('model'), 'dossier_chars': doss and len(doss)}
            else:
                result['llm_audit'] = {'used': False, 'reason': 'audit unparsable/insufficient'}
        else:
            result['llm_audit'] = {'used': False, 'reason': 'audit gate closed (set GREYHOUND_ALLOW_LLM_AUDIT=1 to opt in)' if not _la.audit_allowed() else 'endpoint down (deterministic path)'}
    except Exception as _ae:
        result['llm_audit'] = {'used': False, 'reason': f'stage error: {str(_ae)[:120]}'}
    try:
        from greyhound_publisher import publish_from_greyhound
        md = publish_from_greyhound(title=f'Master Guide — {query[:100]}', executive_brief=None, greyhound_result=result, write_to=str(write_path), output_spec=output_spec)
        result['master_guide'] = {'path': str(write_path), 'chars': len(md), 'written': write_path.exists(), 'preview': md[:_GUIDE_PREVIEW]}
    except Exception as pe:
        result.setdefault('warnings', []).append(f'publisher failed: {str(pe)[:200]}')
    rr = result.get('run_report')
    if isinstance(rr, dict):
        try:
            report_path = write_path.with_suffix(write_path.suffix + '.run-report.json')
            report_path.write_text(json.dumps(rr, indent=2, default=str), encoding='utf-8')
            result['run_report_path'] = str(report_path)
        except Exception as re_:
            result.setdefault('warnings', []).append(f'run report write failed: {str(re_)[:140]}')
    if result.get('master_guide', {}).get('written'):
        try:
            _corpus_related(query, write_path)
            result['master_guide']['corpus_related_added'] = True
        except Exception as ce:
            result.setdefault('warnings', []).append(f'corpus-related failed: {str(ce)[:140]}')
    try:
        builder = Path(__file__).with_name('greyhound_site_builder.py')
        if result.get('master_guide', {}).get('written') and builder.exists():
            site_out = write_path.with_name(write_path.stem + '_site')
            pr = subprocess.run([sys.executable, str(builder), str(write_path), '-o', str(site_out), '--max-images', '40'], capture_output=True, text=True, timeout=150)
            result['site'] = {'path': str(site_out), 'pages': len(list(site_out.glob('*.html'))), 'built': (site_out / 'index.html').exists(), 'engine_tail': (pr.stdout or '').strip()[-200:]}
            try:
                import json as _json
                _guard = _json.loads((site_out / 'guardrails.json').read_text())
                result['site']['guardrails'] = _guard
                if not _guard.get('ok'):
                    result['site']['built'] = False
                    result.setdefault('warnings', []).append('site guardrails FAILED: ' + ', '.join((k for k, c in _guard['checks'].items() if not c['pass'])))
            except Exception:
                pass
            if pr.returncode != 0:
                result.setdefault('warnings', []).append(f"site builder rc={pr.returncode}: {(pr.stderr or '')[-160:]}")
    except Exception as se:
        result.setdefault('warnings', []).append(f'site build failed (isolated): {str(se)[:160]}')
    return result

def _guarded_url_scrape(url: str):
    if not _DEEP_LOCK.acquire(blocking=False):
        return {'ok': False, 'error': 'another run holds the browser', 'url': url}
    try:
        return research_scrape(url, max_chars=0)
    finally:
        _DEEP_LOCK.release()

def _inline_deep(query: str, categories, max_results: int, budget: float, write_path: Path, slot_note: str, pinned=None):
    if not _DEEP_LOCK.acquire(blocking=False):
        return {'busy': True}
    try:
        result = _execute_deep(query, categories, max_results, budget, pinned=pinned)
    finally:
        _DEEP_LOCK.release()
    return _attach_guide(result, query, write_path)
_TASK_RE = re.compile('^(?:task-)?([1-4])$', re.IGNORECASE)
_SLOT_ORDER = ('task-1', 'task-2', 'task-3', 'task-4')

def _cdp_answers(port: int) -> bool:
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/version', timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False

def _slot_reg_entry(tid: str) -> dict:
    try:
        reg = pipeline.task_registry()
        return (reg or {}).get(tid) or {}
    except Exception:
        return {}

def _slot_busy_reason(tid: str, port: int) -> str:
    entry = _slot_reg_entry(tid)
    pid = entry.get('pid')
    if isinstance(pid, int) and pid > 0 and (pid != os.getpid()):
        try:
            os.kill(pid, 0)
            return f"slot {tid} :{port} owned by live session {entry.get('owner_session') or 'unknown'} (pid {pid})"
        except ProcessLookupError:
            pass
        except PermissionError:
            return f"slot {tid} :{port} owned by live session {entry.get('owner_session') or 'unknown'} (pid {pid})"
    if not entry and _cdp_answers(port):
        return f'a browser is already running on {tid} port {port} (unregistered)'
    return ''

def _bind_slot(task_id: str='') -> tuple:
    candidates = []
    if task_id:
        m = _TASK_RE.match(str(task_id).strip())
        if not m:
            raise ValueError(f"bad task_id {task_id!r}: use 'task-1'..'task-4' (or '1'..'4')")
        candidates = [f'task-{m.group(1)}']
    else:
        candidates = ['task-3'] + [t for t in _SLOT_ORDER if t != 'task-3']
    import browser_ports as _bports
    conflicts = []
    for tid in candidates:
        port = int(_bports.resolve(task=tid)['port'])
        reason = _slot_busy_reason(tid, port)
        if reason:
            conflicts.append(reason)
            if task_id:
                break
            continue
        try:
            pipeline.task_registry(assign=tid, task_id=tid)
        except Exception:
            pass
        os.environ['RESEARCH_TASK'] = tid
        note = f'task slot assigned: {tid} (port {port}, registry written)'
        if len(candidates) > 1:
            taken = [c for c in conflicts]
            note += f"; skipped: {'; '.join(taken)}" if taken else '; no other live greyhound sessions'
        return (tid, note)
    raise ValueError('no free browser slot: ' + '; '.join(conflicts))

def _slot_map() -> Dict[str, dict]:
    import browser_ports as _bports
    reg = {}
    try:
        reg = pipeline.task_registry() or {}
    except Exception:
        pass
    out: Dict[str, dict] = {}
    for tid in _SLOT_ORDER:
        try:
            port = int(_bports.resolve(task=tid)['port'])
        except Exception:
            continue
        entry = reg.get(tid) or {}
        pid = entry.get('pid')
        owner_alive = False
        if isinstance(pid, int) and pid > 0 and (pid != os.getpid()):
            try:
                os.kill(pid, 0)
                owner_alive = True
            except OSError:
                owner_alive = False
        out[tid] = {'port': port, 'cdp_alive': _cdp_answers(port), 'owner_session': entry.get('owner_session', ''), 'owner_pid': pid if isinstance(pid, int) else None, 'owner_alive': owner_alive}
    return out

def _deep_worker(run_id: str, query: str, categories: Optional[List[str]], max_results: int, budget: float, write_path: Path, slot_note: str, pinned=None) -> None:
    started = time.time()
    if not _DEEP_LOCK.acquire(blocking=True, timeout=2.0):
        _set_run(run_id, status='failed', error='could not take the browser within 2s — another run holds it', elapsed_s=round(time.time() - started, 1))
        return
    try:
        result = _execute_deep(query, categories, max_results, budget, pinned=pinned)
        result = _attach_guide(result, query, write_path)
        guide = result.get('master_guide') or {}
        fill = result.get('fill_lane') or {}
        rr = result.get('run_report') or {}
        _set_run(run_id, status='done', elapsed_s=round(time.time() - started, 1), pages_ok=len(result.get('pages_fetched', [])), pages_skipped=len(result.get('skipped_pages', [])), findings=len(result.get('findings', [])), sources=len(result.get('sources', [])), fill_lane={'triggered': bool(fill.get('triggered')), 'scraped': fill.get('scraped', 0), 'accepted': fill.get('accepted', 0), 'quarantined': fill.get('quarantined', 0), 'rejected': fill.get('rejected', 0)}, relevance={'accepted': rr.get('accepted_count', 0), 'quarantined': rr.get('quarantined_count', 0), 'rejected': rr.get('rejected_count', 0), 'candidate_count': rr.get('candidate_count', 0), 'judge_ran': result.get('judge_ran', False)}, run_report_path=result.get('run_report_path'), master_guide={'path': str(write_path), 'chars': guide.get('chars'), 'written': guide.get('written')}, preview=(guide.get('preview') or '')[:_GUIDE_PREVIEW], site=result.get('site', {}), skip_sample=[str((s.get('reason') if isinstance(s, dict) else s) or '')[:120] for s in (rr.get('skipped_pages') or result.get('skipped_pages') or [])[:5]], warnings_tail=[str(w)[:160] for w in (result.get('warnings') or [])[-6:]], slot=slot_note)
    except Exception as e:
        _set_run(run_id, status='failed', error=f'{type(e).__name__}: {str(e)[:300]}', elapsed_s=round(time.time() - started, 1))
    finally:
        _DEEP_LOCK.release()

def dispatch(name: str, args: dict) -> dict:
    if name in _REMOVED:
        return {'ok': False, 'removed': True, 'tool': name, 'use_instead': _REMOVED[name], 'note': 'Renamed tools: greyhound + greysearch_health are the only surfaces. This is a rename hint, not something to retry.'}
    if name == 'greyhound':
        url = str(args.get('url') or '').strip()
        query = str(args.get('query') or '').strip()
        keep_raw = bool(args.get('keep_raw_html', False))
        if url:
            try:
                _tid, _note = _bind_slot(str(args.get('task_id') or ''))
            except ValueError as be:
                return {'ok': False, 'busy': True, 'error': str(be), 'browser_slots': _slot_map()}
            if _DEEP_LOCK.locked():
                return _busy_response('one-URL scrape needs the private browser')
            fut = _BROWSER_EXEC.submit(_guarded_url_scrape, url)
            try:
                r = fut.result(timeout=180)
            except _FutTimeout:
                return _busy_response('one-URL scrape waited >180s behind an active run')
            if isinstance(r, dict) and (not keep_raw):
                r.pop('html', None)
            return _redacted(r)
        if not query:
            return {'ok': False, 'error': 'provide query (research question) or url (single-page scrape)'}
        max_results = max(1, min(int(args.get('max_results', DEFAULT_MAX_RESULTS)), 25))
        categories = args.get('categories')
        pinned = args.get('pinned_sources') or []
        if pinned and (not isinstance(pinned, list)):
            pinned = [pinned]
        scrape_all = bool(args.get('scrape_all', True))
        if not scrape_all:
            r = research_search(query, category=categories[0] if categories else 'general', max_results=max_results)
            return _redacted({'mode': 'search-only (scrape_all=false)', **r})
        write_path = _resolve_guide_path(args.get('write_guide_to'), query)
        try:
            tid, slot_note = _bind_slot(str(args.get('task_id') or ''))
        except ValueError as be:
            return {'ok': False, 'busy': True, 'error': str(be), 'browser_slots': _slot_map()}
        budget = float(args.get('max_seconds', 300.0))
        _TIER = str(args.get('tier') or '').strip().lower()
        _TIER_CAPS = {'brief': (3, 240.0), 'standard': (4, 300.0), 'deep': (6, 420.0), 'report': (8, 540.0)}
        if _TIER in _TIER_CAPS:
            _tp, _tb = _TIER_CAPS[_TIER]
            if 'max_results' not in args:
                max_results = _tp
            if 'max_seconds' not in args:
                budget = _tb
        background = bool(args.get('background', True))
        if not background:
            if _DEEP_LOCK.locked():
                return _busy_response('background=false deep run')
            fut = _BROWSER_EXEC.submit(_inline_deep, query, categories, max_results, budget, write_path, slot_note, pinned)
            try:
                result = fut.result(timeout=float(budget) + 90)
            except _FutTimeout:
                return _busy_response('deep run queued longer than its budget')
            if isinstance(result, dict) and result.get('busy'):
                return _busy_response('deep run (browser was busy)')
            if slot_note:
                result.setdefault('warnings', []).append(slot_note)
            return _redacted(_shape_response(result, keep_raw))
        if _DEEP_LOCK.locked():
            return _busy_response('deep run')
        run_id = f'run-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}'
        with _RUN_GUARD:
            _RUNS[run_id] = {'run_id': run_id, 'query': query, 'status': 'running', 'started_ts': time.time(), 'started_at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'guide_path': str(write_path), 'slot': slot_note}
        _BROWSER_EXEC.submit(_deep_worker, run_id, query, categories, max_results, budget, write_path, slot_note, pinned)
        resp = {'ok': True, 'run_id': run_id, 'status': 'running', 'started_at': _RUNS[run_id]['started_at'], 'guide_path': str(write_path), 'how_to_check': 'call greyhound_health — runs[] carries the digest; when status=done, read guide_path. NEVER re-call greysearch with tweaked args while a run is active.'}
        if slot_note:
            resp['slot'] = slot_note
        return _redacted(resp)
    if name == 'greyhound_health':
        bridge = get_bridge()
        base = bridge.health_check()
        try:
            base['browser_slots'] = _slot_map()
        except Exception:
            pass
        try:
            mgr = SearXNGEngineManager()
            base['searx_space_instances'] = mgr._discover_public_instances(max_instances=3)
        except Exception as e:
            base['searx_space_instances'] = f'error: {e}'
        with _RUN_GUARD:
            runs = [dict(r) for r in sorted(_RUNS.values(), key=lambda d: d.get('started_ts', 0))]
        trimmed = []
        for r in runs[-_RUNS_KEEP:]:
            rr = {k: v for k, v in r.items() if k != 'preview'}
            if r.get('preview'):
                rr['preview'] = r['preview'][:400]
            trimmed.append(rr)
        base['greyhound_runs'] = {'note': 'background greyhound digests; when status=done, read the master_guide/preview or open guide_path directly', 'runs': trimmed}
        return _redacted(base)
    raise ValueError(f'Unknown tool: {name}  (greyhound exposes exactly: greysearch, greysearch_health)')

def _initialize_result() -> dict:
    return {'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'greyhound', 'version': '1.0.0'}}

def reply(rid, result=None, error=None):
    resp = {'jsonrpc': '2.0', 'id': rid}
    if error is not None:
        resp['error'] = error
    else:
        resp['result'] = result
    sys.stdout.write(json.dumps(resp) + '\n')
    sys.stdout.flush()

def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        if req.get('method') == 'initialize':
            reply(req['id'], _initialize_result())
        elif req.get('method') == 'notifications/initialized':
            pass
        elif req.get('method') == 'tools/list':
            reply(req['id'], {'tools': TOOLS})
        elif req.get('method') == 'tools/call':
            try:
                result = dispatch(req['params'].get('name', ''), req['params'].get('arguments', {}))
                reply(req['id'], {'content': [{'type': 'text', 'text': json.dumps(result)}]})
            except Exception as e:
                reply(req['id'], error={'code': -32000, 'message': f'{type(e).__name__}: {e}'})
                traceback.print_exc(file=sys.stderr)
        elif 'id' in req:
            reply(req['id'], error={'code': -32601, 'message': 'Method not found'})
if __name__ == '__main__':
    main()