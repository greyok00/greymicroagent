from __future__ import annotations
import json
import re
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
BANK = ROOT / 'data' / 'kali-bank.json'
_CACHE = {'loaded': None}

def _bank():
    if BANK is None or not Path(BANK).exists():
        raise FileNotFoundError(f'{BANK} missing — ship the lab-only bank JSON beside this module')
    stamp = (str(BANK), BANK.stat().st_mtime, BANK.stat().st_size)
    if _CACHE['loaded'] and _CACHE['loaded'][0] == stamp:
        return _CACHE['loaded'][1]
    data = json.loads(BANK.read_text())
    tools = data.get('tools', [])
    index = {'generated': data.get('generated', ''), 'lab_only': data.get('lab_only', ''), 'tools': tools, 'grammar': data.get('placeholder_grammar', {}), 'phases': {}}
    for t in tools:
        index['phases'].setdefault(str(t.get('phase', '?')), []).append(t)
    _CACHE['loaded'] = (stamp, index)
    return index

def _matches(tool, text):
    return bool(re.search(re.escape(text), str(tool), re.I))

def bank_query(query: str='', tool: str='', phase: str='', slot: str='', limit: int=6) -> dict:
    try:
        idx = _bank()
    except Exception as e:
        return {'ok': False, 'error': f'bank load failed: {e}'}
    limit = max(1, min(int(limit or 6), 12))
    if slot or (query and re.fullmatch('\\{\\{\\s*\\w+\\s*\\}\\}', query.strip())):
        tok = re.sub('[{} ]', '', slot or query).strip()
        g = idx['grammar'].get(tok, '')
        if not g:
            return {'ok': True, 'output': 'no slot ' + tok + '. known: ' + ', '.join(('{{' + k + '}}' for k in sorted(idx['grammar'])))}
        uses = sorted({t['name'] for t in idx['tools'] for c in t.get('commands', []) if tok in (c.get('vars', []) or [])})
        return {'ok': True, 'output': f"slot {{{{{tok}}}}} = {g}\nappears in {len(uses)} forms, e.g. {' · '.join(uses[:5])}"}
    if phase != '':
        tools = idx['phases'].get(str(phase))
        if not tools:
            return {'ok': False, 'error': f'no phase {phase!r} (0-9)'}
        out = [f'phase {phase}: {len(tools)} tools']
        for t in tools[:limit]:
            out.append(f"  {t['name']} · {len(t.get('commands', []))} forms")
        return {'ok': True, 'output': '\n'.join(out)}
    if tool:
        hits = [t for t in idx['tools'] if _matches(t['name'], tool) or _matches(t['slug'], tool)]
        if not hits:
            return {'ok': False, 'error': f'no bank tool matches {tool!r}'}
        t = hits[0]
        rows = [f"{t['name']} (slug {t['slug']}) · phase {t['phase']}", f"purpose: {t.get('purpose', '')}"]
        for i, c in enumerate(t.get('commands', [])[:limit], 1):
            rows.append(f"[{i}] {c.get('title', '')}")
            for ln in c['cmd'].split('\n'):
                rows.append(f'    $ {ln}')
            if c.get('vars'):
                rows.append('    slots: ' + ', '.join(('{{' + v + '}}' for v in c['vars'])))
        return {'ok': True, 'output': '\n'.join(rows)}
    q = (query or '').strip()
    if not q:
        nt = len(idx['tools'])
        nc = sum((len(t.get('commands', [])) for t in idx['tools']))
        return {'ok': True, 'output': f'Kali command bank · LAB-ONLY · {nt} tools · {nc} forms · usage: kali_bank(query=… | tool=… | phase=0..9 | slot=…)'}
    scored = []
    for t in idx['tools']:
        if _matches(t['name'], q) or _matches(t['slug'], q):
            best = 0
        elif _matches(t.get('purpose', ''), q):
            best = 1
        else:
            for c in t.get('commands', []):
                if _matches(c['cmd'], q):
                    best = 2
                    break
            else:
                continue
        scored.append((best, t))
    if not scored:
        return {'ok': False, 'error': f'no bank match for {q!r}'}
    scored.sort(key=lambda x: x[0])
    out = [f'matches for {q!r}: {len(scored)} (top {limit})']
    for _, t in scored[:limit]:
        out.append(f"  {t['name']} · phase {t['phase']} · {(t.get('purpose') or '')[:100]}")
    return {'ok': True, 'output': '\n'.join(out)}