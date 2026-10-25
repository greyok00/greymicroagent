from __future__ import annotations
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
NOT_CAPTURED = 'DATA NOT CAPTURED'
MASTER_GUIDE_TEMPLATE = '# {title}\n\n> **Executive Brief:** {executive_brief}\n\n---\n\n## 1. Deep-Dive Overview & Context\n{overview}\n\n## 2. Full Technical & Feature Breakdown\n{breakdown}\n\n## 3. Comparative Data & Specs\n{comparative}\n\n## 4. Complete Actionable Steps / Execution Guide\n{steps}\n\n## 5. Primary Sources & Media Links\n{sources}\n'
_CODE_INCOMPLETE = re.compile('#\\s*TODO|//\\s*\\.\\.\\.|\\.\\.\\.\\s*rest of code|#\\s*add logic here')
_NAV_LINE = re.compile('(?i)(skip to content|open our|about us|our etfs|merch\\b|contact|subscribe|tune into|sign in|log in|menu\\b|invest now|open education|\\b×\\b|cookie|accept all)')

def _trim_leading_nav(text: str) -> str:
    lines = (text or '').split('\n')
    i = 0
    broke = False
    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        words = len(s.split())
        navish = bool(_NAV_LINE.search(s))
        if words >= 9 and len(s) >= 60 and (not navish):
            broke = True
            break
        if words < 9 and (navish or len(s) < 40):
            continue
        broke = True
        break
    out = '\n'.join(lines[i:]) if broke else ''
    return out.strip() or (text or '').strip()

def _md_links(links: List[Dict[str, str]], limit: int=80) -> str:
    items = links if not limit else links[:limit]
    return '\n'.join((f"- [{(l.get('text') or l.get('href'))[:120]}]({l['href']})" for l in items if l.get('href')))

def _md_images(images: List[Dict[str, str]], limit: int=0) -> str:
    items = images if not limit else images[:limit]
    return '\n'.join((f"![{i.get('alt') or 'image'}]({i['src']})" for i in items if i.get('src')))
_IMG_EMOJI_ALT = re.compile('^:[\\w-]+:$')
_IMG_CHROME = re.compile('(?i)(logo|icon|avatar|badge|banner|button|sprite|favicon|placeholder|spacer|pixel|tracking|advertisement|\\bad\\b|social|share)')

def _content_images(images: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    kept: List[Dict[str, Any]] = []
    for im in images:
        src = (im.get('src') or '').strip()
        alt = (im.get('alt') or '').strip()
        if not src.startswith('http'):
            continue
        if src.lower().endswith('.svg'):
            continue
        if _IMG_EMOJI_ALT.match(alt) or 'emoji' in src.lower():
            continue
        if _IMG_CHROME.search(alt + ' ' + src):
            continue
        w, h = (int(im.get('w') or 0), int(im.get('h') or 0))
        if not (w and h):
            continue
        if w < 200 and h < 200:
            continue
        if h < 450 and w / h >= 2.8:
            continue
        kept.append(im)
    return kept

def _md_videos(videos: List[Dict[str, str]]) -> str:
    return '\n'.join((f"- [{v.get('title') or v['src']}]({v['src']})" for v in videos if v.get('src')))

def _md_audios(audios: List[Dict[str, str]]) -> str:
    items = audios
    return '\n'.join((f'''<audio controls><source src="{a['src']}" type="audio/mpeg"></audio> {a.get('title', '')}''' for a in items if a.get('src')))

def _md_pdfs(pdfs: List[Dict[str, str]]) -> str:
    items = pdfs
    return '\n'.join((f"- [{a.get('title') or a['src']}]({a['src']})" for a in items if a.get('src')))

def _md_canvases(canvases: List[Dict[str, int]]) -> str:
    items = canvases
    if not items:
        return ''
    return '\n'.join((f"- Canvas {i.get('width', 0)}x{i.get('height', 0)}" for i in items))

def _md_iframes(iframes: List[Dict[str, str]]) -> str:
    items = iframes
    return '\n'.join((f'''<iframe src="{i['src']}" title="{i.get('title', '')}" width="560" height="315"></iframe>''' for i in items if i.get('src')))

def _md_table(table: Dict[str, Any]) -> str:
    rows = table.get('rows') or []
    if not rows:
        return ''
    header = [str(h).replace('\n', ' ').replace('|', '\\|') for h in rows[0]]
    sep = ['---'] * len(header)
    lines = ['| ' + ' | '.join(header) + ' |', '| ' + ' | '.join(sep) + ' |']
    for r in rows[1:]:
        r = (list(r) + [''] * len(header))[:len(header)]
        cells = [str(c).replace('\n', ' ').replace('|', '\\|') for c in r]
        lines.append('| ' + ' | '.join(cells) + ' |')
    if table.get('caption'):
        lines.append(f"\n*{table['caption']}*")
    return '\n'.join(lines)

def _clean_prose(text: str) -> str:
    text = re.sub('\\s(?:class|style|id)\\s*=\\s*"[^"]*"', '', text)
    text = re.sub('[ \\t]{2,}', ' ', text)
    text = re.sub('\\n{3,}', '\n\n', text)
    return text.strip()
BREAKDOWN_PROSE_CAP = 40000
_TRUNCATION_NOTE = '*[Truncated: this section shows the first {kept:,} of {total:,} characters — the cut lands at the last clean paragraph or word boundary; the full source text remains in the run report JSON beside the guide.]*'

def _cap_section_prose(text: str, cap: int=BREAKDOWN_PROSE_CAP) -> str:
    if not text or len(text) <= cap:
        return text
    total = len(text)
    cut = text[:cap]
    para = cut.rfind('\n\n')
    if para > cap // 2:
        cut = cut[:para]
    else:
        sp = cut.rfind(' ')
        if sp > cap // 2:
            cut = cut[:sp]
    kept = len(cut.strip())
    return cut.strip() + '\n\n' + _TRUNCATION_NOTE.format(kept=kept, total=total)

def _paragraphs(text: str, count: int=2) -> List[str]:
    blocks = [b.strip() for b in re.split('\\n\\s*\\n', text or '') if b.strip()]
    out = []
    for b in blocks:
        if len(out) >= count:
            break
        if len(b) > 120:
            out.append(b)
    return out

def _is_stepish(paragraph: str) -> bool:
    head = paragraph.strip().lower()
    if re.match('^(step\\s+\\d+|\\d+[\\).:]\\s|\\d+\\.\\d+\\s)', head):
        return True
    if re.match('^(first|second|third|next|then|finally|after\\s+that|to\\s+start|begin\\s+by|start\\s+by)\\b', head):
        return True
    return False
_BRIEF_SKIP_TO = re.compile('(?i)skip to (?:search|footer|content|navigation)')

def _nav_chain(s: str) -> bool:
    words = s.split()
    if len(words) < 8 or len(s) > 400:
        return False
    caps = sum((1 for w in words if w[:1].isupper() or w.isupper()))
    no_period = not re.search('[a-z],|\\.', s.replace('.', '.', 0))
    has_period = bool(re.search('\\.\\s', s))
    return caps >= len(words) * 0.6 and (not has_period)
from page_clean import _strip_nav_glue

def _clean_brief_text(text: str) -> str:
    out = _clean_prose(text or '')
    lines = []
    for ln in out.split('\n'):
        s = ln.strip()
        if s and (_NAV_LINE.search(s) or _is_chrome_line(s)):
            continue
        if s and (len(s) <= 400 and (_BRIEF_SKIP_TO.search(s) or _nav_chain(s))):
            continue
        lines.append(ln)
    return _strip_nav_glue(_clean_prose('\n'.join(lines)))
_CHROME_LINE = re.compile('(?i)(we use cookies?|accept all cookies?|cookie (policy|notice|consent)|all rights reserved|subscribe (to our )?newsletter|follow us on|share this (article|page|post)|skip to (main )?content|sign in|log in|create (free )?account|back to top|just a moment|checking your browser|enable javascript)')

def _is_chrome_line(s: str) -> bool:
    return bool(_CHROME_LINE.search(s)) and len(s) < 220
_RFC822_DATE = re.compile('(?i)\\b(?:(?:mon|tue|wed|thu|fri|sat|sun)[a-z]{0,6},\\s+)?\\d{1,2}\\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]{0,7}\\.?\\s+\\d{4}\\s+\\d{1,2}:\\d{2}(?::\\d{2})?\\s+(?:[+-]\\d{4}|[A-Z]{2,5})\\b')
_MAIL_FIELD_LINE = re.compile('(?im)^(?:subject|from|to|cc|bcc|date|message-id|reply-to|mailing-list|list-[a-z-]+|delivered-to|in-reply-to|references|x-[a-z-]+|content-[a-z-]+)\\s*:.*$')
_MAIL_REPLY_WROTE = re.compile('(?i)\\bon\\s+(?:[a-z]{3},\\s+)?\\d{1,2}\\s+[a-z]{3}\\.?\\s+\\d{4}[^.\\n]{0,120}?\\bwrote:\\s*')
_MAIL_GREETING = re.compile("^[ \\t]*[A-Z][A-Za-z'.-]+(?:\\s+[A-Z]\\.)?(?:\\s+[A-Z][A-Za-z'-]+)+,\\s+")
_MAIL_HEADER_SHAPE = re.compile('(?i)\\b(?:re|fwd|fw|aw|es)\\s*:|\\[(?:bug|patch|rfc)\\s*#?\\d+\\]|\\bmessage-id\\b|\\bdelivered-to\\b|\\bwrote\\s*:')
_CONSENT_GLUE = re.compile("(?i)(?:i|we|you|\\s)*(?:do\\s+not\\s+|(?:don't|dont)\\s+)?(?:agree|decline|accept(?:\\s+all)?|reject(?:\\s+all)?|manage\\s+(?:my\\s+)?preferences?|change\\s+my\\s+preferences?|customize|cookie\\s+(?:settings|preferences)?)(?=(?-i:[A-Z]))")
_MAIL_CONSENT_TAIL = re.compile('(?i)\\b(?:i|we)\\s+(?:agree|decline|accept(?:\\s+all)?)\\b|\\b(?:change|manage|customize)\\s+(?:my\\s+)?preferences\\b|\\b(?:accept|reject)\\s+all\\b|\\bcookie\\s+(?:settings|preferences)\\b')
_REPO_STAR_BREADCRUMB = re.compile('(?i)(?:^|\\s)/\\s+[^()\\n/]{2,80}\\(\\s*\\d+\\s*\\)\\s*stars?\\s*\\d*')
_REPO_STAR_PLAIN = re.compile('(?i)\\(?\\s*\\d+\\s*\\)?\\s*stars?\\s*\\d*(?:\\s*\\(\\s*\\d+\\s*\\))?(?=\\s*(?:·|history))')
_REPO_HISTORY = re.compile('(?i)\\(\\s*\\d+\\s*\\)\\s*·\\s*history\\s+\\d+\\s+commits?\\b')
_REPO_FOLDERS_BLOCK = re.compile('(?i)folders\\s+and\\s+files\\b(?:[\\s\\S]{0,600}?\\binitial\\s+commit\\b)+(?:\\s+[a-z][\\w.\\-/]{0,39}(?=\\s+[a-z]))?')
_REPO_TABLE_HEAD = re.compile('(?i)\\bname\\s+last\\s+commit\\s+message(?:\\s+last\\s+commit\\s+(?:date|time))?\\b')
_POSTED_ON_BULLET = re.compile('(?i)\\bposted\\s+on\\s+[a-z]+\\.?\\s+(?:\\d{1,2}\\s*,?\\s*)?\\d{4}\\s*[•·]\\s*')
_ADJACENT_DUP = re.compile('(\\b[^.!?\\n]{12,120})\\1')
_GLUE_ATTR = re.compile('\\*{0,2}\\(\\s*per\\s+[a-z0-9.\\-]+\\.[a-z]{2,}\\s*\\)\\*{0,2}', re.IGNORECASE)

def _strip_mail_header_junk(text: str) -> str:
    if not _MAIL_HEADER_SHAPE.search(text):
        return text
    date = _RFC822_DATE.search(text[:400])
    lede_cut = False
    out = text
    if date:
        head = text[:date.end()]
        if _MAIL_HEADER_SHAPE.search(head):
            rest = text[date.end():].lstrip()
            rest = _MAIL_GREETING.sub('', rest, count=1)
            out = rest
            lede_cut = True
    out = _MAIL_REPLY_WROTE.sub(' ', out)
    out = _MAIL_FIELD_LINE.sub(' ', out)
    if lede_cut:
        out = _RFC822_DATE.sub(' ', out)
    return out

def _strip_consent_glue(text: str) -> str:
    if not re.search('(?i)\\b(?:agree|decline|preferences|accept|reject|customize|consent|cookie)\\b', text):
        return text
    glued, n = _CONSENT_GLUE.subn(' ', text)
    if n == 0:
        return text
    glued = _MAIL_CONSENT_TAIL.sub(' ', glued)
    return glued

def _strip_repo_chrome(text: str) -> str:
    if not ('folder' in text.lower() and 'files' in text.lower() and ('initial commit' in text.lower() or 'last commit message' in text.lower() or _REPO_STAR_BREADCRUMB.search(text))):
        return text
    out = _REPO_STAR_BREADCRUMB.sub(' ', text)
    out = _REPO_STAR_PLAIN.sub(' ', out)
    out = _REPO_HISTORY.sub(' ', out)
    out = re.sub('(?i)\\bfolders\\s+and\\s+files\\b', ' ', out)
    out = _REPO_FOLDERS_BLOCK.sub(' ', out)
    out = _REPO_TABLE_HEAD.sub(' ', out)
    out = re.sub('(?i)(?:\\s+[\\w.\\-/]{1,40}\\s+initial\\s+commit\\b)+', ' ', out)
    return out

def _strip_page_glue(text: str) -> str:
    out = _strip_mail_header_junk(text)
    out = _strip_consent_glue(out)
    out = _strip_repo_chrome(out)
    out = _POSTED_ON_BULLET.sub(' ', out)
    if out != text:
        out = _ADJACENT_DUP.sub('\\1', out)
        out = re.sub('[•·|\\[\\]]', ' ', out)
        out = re.sub('[ \\t]{2,}', ' ', out)
    return out.strip()

def _has_glue_markers(text: str) -> bool:
    low = text.lower()
    if 'folders' in low and 'files' in low and ('initial commit' in low or 'last commit message' in low):
        return True
    if any((w in low for w in ('agree', 'decline', 'preferences', 'accept', 'reject', 'customize', 'consent', 'cookie'))):
        return True
    if 'wrote:' in low or 'message-id' in low or 'delivered-to' in low or ('posted on' in low):
        return True
    if _RFC822_DATE.search(text):
        return True
    return False
_BARE_FOOTNOTE = re.compile('\\s*\\[\\s*(?:\\d+|note\\s+\\d+|[a-z])\\s*\\]', re.IGNORECASE)
_JUMP_BACKLINK_QUOTED = re.compile('(?is)\\bjump up to:?\\s*(?:[a-z]\\s+){0,4}"[^"]*"\\s*[.,;]?\\s*')
_JUMP_BACKLINK_BARE = re.compile('(?im)\\bjump up to:?.*$')
_JUMP_ARROW_LINE = re.compile('(?m)^\\^.*$')

def _strip_refs_junk(text: str) -> str:
    if not text:
        return ''
    low = text.lower()
    if 'jump up to' not in low and 'citation needed' not in low and (not _BARE_FOOTNOTE.search(text)) and (not _has_glue_markers(text)):
        return text
    out = _JUMP_BACKLINK_QUOTED.sub(' ', text)
    out = _JUMP_BACKLINK_BARE.sub(' ', out)
    out = _JUMP_ARROW_LINE.sub(' ', out)
    out = _BARE_FOOTNOTE.sub('', out)
    out = re.sub('(?i)\\(\\s*citation needed\\s*\\)', ' ', out)
    out = _strip_page_glue(out)
    out = re.sub('[ \\t]{2,}', ' ', out)
    return out.strip()
_MIN_SALVAGE = 40

def _refs_candidate(raw: str) -> Optional[str]:
    scrubbed = _strip_refs_junk(raw)
    cleaned = _clean_brief_text(scrubbed)
    if scrubbed != raw and len(''.join(cleaned.split())) < _MIN_SALVAGE:
        return None
    return cleaned

def _brief_candidate(text: str) -> Optional[str]:
    raw = text or ''
    if _GLUE_ATTR.search(raw):
        frags = [f for f in _GLUE_ATTR.split(raw) if f.strip()]
        if len(frags) >= 2:
            best: Optional[str] = None
            for frag in frags:
                cand = _refs_candidate(frag)
                if cand and (best is None or len(cand) > len(best)):
                    best = cand
            return best
        raw = _GLUE_ATTR.sub(' ', raw)
    return _refs_candidate(raw)

def _synthesize_brief(result: Dict[str, Any]) -> str:
    findings = result.get('findings') or []
    pages = result.get('pages_fetched') or []
    parts: List[str] = []
    for f in findings:
        if len(parts) >= 4:
            break
        cand = _brief_candidate(f.get('text', ''))
        if not cand:
            continue
        dom = (f.get('source_domains') or [''])[0]
        src = f' *(per {dom})*' if dom else ''
        parts.append(f'{cand}{src}')
    if not parts and pages:
        clean = pages[0].get('clean') or {}
        raw = _trim_leading_nav(clean.get('body_text') or _page_clean_filtered_fallback(pages[0]))
        scrubbed = _strip_refs_junk(raw)
        paras = _paragraphs(_clean_brief_text(scrubbed), 1)
        if paras and (scrubbed == raw or len(''.join(paras[0].split())) >= _MIN_SALVAGE):
            para = paras[0]
            if _GLUE_ATTR.search(para):
                para = _brief_candidate(para) or ''
            if para:
                parts.append(para)
    if parts:
        body = ' '.join(parts[:3])
        n_pages = len(pages)
        body += f'\n\nCompiled live from {n_pages} accepted source(s) via the local SearXNG + searx.space automatic ladder and the private stealth browser, filtered by the two-stage relevance gate. Every section carries its source;'
        base = _clean_prose(body)
    else:
        base = f"{NOT_CAPTURED} — the research run returned no accepted source text. See the run's skipped_pages / run-report fields for exactly which pages were rejected or quarantined, and why."
    return base

def _synthesize_overview(result: Dict[str, Any]) -> str:
    findings = result.get('findings') or []
    pages = result.get('pages_fetched') or []
    paras: List[str] = []
    if findings:
        lead, support = ([], [])
        for f in findings[:6]:
            cand = _brief_candidate(f.get('text', '')) or _clean_brief_text(f.get('text', ''))
            dom = (f.get('source_domains') or [''])[0]
            line = f'{cand} ({dom})'
            (lead if not lead else support).append(line)
        if lead:
            paras.append(lead[0])
        if support:
            paras.append(' '.join(support[:4]))
    if not paras and pages:
        clean = pages[0].get('clean') or {}
        raw = _trim_leading_nav(clean.get('body_text') or _page_clean_filtered_fallback(pages[0]))
        paras = _paragraphs(_clean_brief_text(raw), 2)
    if not paras:
        paras.append(f'{NOT_CAPTURED} — full prose for this topic was not captured.')
    searches = result.get('searches') or []
    if searches:
        lanes = '; '.join((f"{s.get('category')}: {s.get('n', 0)} results" for s in searches[:3]))
        paras.append(f'Search coverage for this run — {lanes}.')
    combined = '\n\n'.join(paras)
    return combined

def _page_clean_filtered_fallback(page: Dict[str, Any]) -> str:
    raw = page.get('text', '') or ''
    if not raw:
        return ''
    try:
        import page_clean
        cleaned = page_clean.clean_page({'text': raw, 'raw_text': page.get('raw_text', '') or raw, 'url': page.get('url', '') or ''})
        return cleaned.get('body_text', '') or ''
    except Exception:
        return ''

def extract_steps_from_sources(breakdown_proses: List[str]) -> List[Dict[str, str]]:
    steps: List[Dict[str, str]] = []
    for prose in breakdown_proses:
        for para in re.split('\\n\\s*\\n', prose or ''):
            p = _clean_prose(para).strip()
            if len(p) > 200 and _is_stepish(p):
                title = p.split('.')[0].split('\n')[0][:80]
                if not steps or p[:80].lower() != steps[-1]['title'].lower():
                    steps.append({'title': title, 'detail': p})
    return steps[:20]

def publish(title: str, executive_brief: str, overview: str, breakdown_sections: List[Dict[str, Any]], comparative_tables: List[Dict[str, Any]], steps: List[Dict[str, str]], sources: List[Dict[str, str]], extra_images: Optional[List[Dict[str, str]]]=None, write_to: Optional[str]=None) -> str:
    b_parts: List[str] = []
    for sec in breakdown_sections:
        heading = (sec.get('heading') or 'Source').replace('\n', ' ')
        b_parts.append(f'### {heading}\n')
        prose = _cap_section_prose(_trim_leading_nav(_clean_prose(sec.get('prose', ''))))
        if prose:
            b_parts.append(prose + '\n\n')
        for img in _content_images(sec.get('images', []) or []):
            if img.get('src'):
                b_parts.append(f"![{img.get('alt') or heading[:60]}]({img['src']})\n")
        for tbl in sec.get('tables', []) or []:
            part = _md_table(tbl)
            if part:
                b_parts.append(part + '\n\n')
        for code in sec.get('code_blocks', []) or []:
            body = (code or '').strip()
            if body and (not _CODE_INCOMPLETE.search(body)):
                b_parts.append(f'```\n{body}\n```\n')
        links = _md_links(sec.get('links') or [])
        if links:
            b_parts.append(links + '\n\n')
        for audio in sec.get('audios', []) or []:
            if audio.get('src'):
                b_parts.append(_md_audios([audio]) + '\n\n')
        for pdf in sec.get('pdfs', []) or []:
            if pdf.get('src'):
                b_parts.append(_md_pdfs([pdf]) + '\n\n')
        for canvas in sec.get('canvases', []) or []:
            if canvas:
                b_parts.append(_md_canvases([canvas]) + '\n\n')
        for iframe in sec.get('iframes', []) or []:
            if iframe.get('src'):
                b_parts.append(_md_iframes([iframe]) + '\n\n')
    c_parts: List[str] = []
    seen_tables = set()
    for t in comparative_tables:
        key = ','.join(t.get('caption') or '') + '|' + ','.join((t.get('rows') or [['']])[0] if t.get('rows') else [])
        if key in seen_tables:
            continue
        seen_tables.add(key)
        rendered = _md_table(t)
        if rendered:
            if t.get('caption'):
                c_parts.append(f"**{t['caption']}**\n")
            c_parts.append(rendered + '\n\n')
    s_parts: List[str] = []
    if steps:
        for i, step in enumerate(steps, 1):
            detail = _clean_prose(step.get('detail') or '')
            s_parts.append(f"{i}. **{step.get('title') or f'Step {i}'}**\n{detail}\n")
    else:
        s_parts.append(f'{NOT_CAPTURED} — no procedure-shaped steps were present in the captured sources. Steps are never fabricated from unrelated prose.')
    src_parts: List[str] = []
    for s in sources or []:
        url = (s.get('url') or '').strip()
        name = (s.get('name') or url).strip()
        if url.startswith('http'):
            src_parts.append(f'- [{name}]({url})')
        elif name:
            src_parts.append(f'- {name} — (no URL recorded)')
    if extra_images:
        media_links = _md_images(extra_images)
        if media_links:
            src_parts.append('\n**Retained media:**\n' + media_links)
    videos: List[Dict[str, str]] = []
    for sec in breakdown_sections or []:
        videos.extend(sec.get('videos') or [])
    if videos:
        src_parts.append('\n**Video sources:**\n' + _md_videos(videos))
    rendered = MASTER_GUIDE_TEMPLATE.format(title=title, executive_brief=_clean_prose(executive_brief).strip() or f'{NOT_CAPTURED}.', overview=_clean_prose(overview).strip(), breakdown='\n\n'.join(b_parts).strip(), comparative='\n\n'.join(c_parts).strip() if c_parts else f'**No comparative tables captured.** All table data: {NOT_CAPTURED}.', steps='\n'.join(s_parts).strip(), sources='\n'.join(src_parts).strip() if src_parts else f'- {NOT_CAPTURED}')
    if write_to:
        path = Path(write_to).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding='utf-8')
    return rendered

def publish_from_greyhound(title: str, executive_brief: Optional[str], greyhound_result: Dict[str, Any], write_to: Optional[str]=None, output_spec: Optional[Dict[str, Any]]=None) -> str:
    breakdown_sections: List[Dict[str, Any]] = []
    comparative_tables: List[Dict[str, Any]] = []
    sources: List[Dict[str, str]] = []
    skipped_notes: List[str] = []
    all_pages = greyhound_result.get('pages_fetched', []) + (greyhound_result.get('all_scraped_pages') or [])
    seen_urls: set = set()
    pages: List[Dict[str, Any]] = []
    for p in all_pages:
        u = p.get('url') or ''
        if u and u in seen_urls:
            continue
        if u:
            seen_urls.add(u)
        rel = p.get('relevance') or {}
        if rel.get('decision') not in (None, 'accept'):
            continue
        pages.append(p)
    rr = greyhound_result.get('run_report') or {}
    skipped_pages = rr.get('skipped_pages')
    if skipped_pages is None:
        skipped_pages = [q if isinstance(q, dict) else {'url': str(q)} for q in greyhound_result.get('quarantined_pages') or []] + [q if isinstance(q, dict) else {'url': str(q)} for q in greyhound_result.get('rejected_pages') or []] + [s if isinstance(s, dict) else {'url': str(s)} for s in greyhound_result.get('skipped_pages') or []]
    for s in skipped_pages:
        url = s.get('url') or ''
        decision = s.get('decision') or 'skipped'
        reason = s.get('reason') or ''
        if url:
            skipped_notes.append(f'- **{decision}** — {url}' + (f' ({reason})' if reason else ''))
    for page in pages:
        heading = (page.get('title') or page.get('url') or 'Untitled')[:140]
        clean = page.get('clean') or {}
        prose = clean.get('body_text') or _page_clean_filtered_fallback(page)
        rel = page.get('relevance') or {}
        allowed = rel.get('allowed_content') or []
        images = page.get('images', [])
        tables = page.get('tables', [])
        code_blocks = page.get('code_blocks', [])
        if 'images' not in allowed and rel.get('decision') == 'accept':
            images = [im for im in images if not re.search('(?i)(logo|icon|avatar|badge|banner|button|sprite|favicon|placeholder|spacer|pixel|tracking|advertisement|\\bad\\b|social|share)', (im.get('alt') or '') + ' ' + (im.get('src') or ''))]
        images = _content_images(images)
        breakdown_sections.append({'heading': heading, 'prose': prose, 'images': images, 'links': page.get('links', []), 'tables': tables, 'code_blocks': code_blocks, 'videos': page.get('videos', []), 'audios': page.get('audios', []), 'pdfs': page.get('pdfs', []), 'canvases': page.get('canvases', []), 'iframes': page.get('iframes', []), 'source_url': page.get('url', '')})
        for t in page.get('tables', []) or []:
            if t.get('rows'):
                comparative_tables.append(t)
        if page.get('url'):
            prov = f'{heading}'
            sc = rel.get('relevance_score')
            if sc is not None:
                prov += f' (relevance {sc})'
            sources.append({'name': prov, 'url': page['url']})
        for pdf in page.get('pdfs', []):
            if isinstance(pdf, dict) and pdf.get('src'):
                sources.append({'name': f"PDF: {pdf.get('title', 'PDF')} ", 'url': pdf['src']})
    limitations_md = ''
    if skipped_notes:
        qw = rr.get('quality_warnings') or []
        lines = ['## Research limitations', 'The two-stage relevance gate (deterministic pre-filter + semantic judge) removed or quarantined the following pages; they do NOT contribute any prose, facts, tables, citations, or images to this guide.', '']
        lines += skipped_notes[:40]
        if len(skipped_notes) > 40:
            lines.append(f'- … and {len(skipped_notes) - 40} more (see the run report JSON next to this guide).')
        if qw:
            lines += ['', '**Quality warnings:**'] + [f'- {w}' for w in qw[:10]]
        limitations_md = '\n'.join(lines)
    audited_facts = ''
    if output_spec and output_spec.get('brief'):
        brief = output_spec['brief']
        facts = output_spec.get('facts') or []
        if facts:
            audited_facts = '\n\n**Audited key facts**\n\n' + '\n'.join((f'- {f}' for f in facts))
    else:
        brief = executive_brief or _synthesize_brief(greyhound_result)
    overview = _synthesize_overview(greyhound_result)
    steps = extract_steps_from_sources([s['prose'] for s in breakdown_sections])
    ladder = greyhound_result.get('ladder_lane') or greyhound_result.get('fill_lane')
    if ladder:
        sources.append({'name': f'search lanes used: {ladder}', 'url': ''})
    md = publish(title=title, executive_brief=brief + audited_facts, overview=overview, breakdown_sections=breakdown_sections, comparative_tables=comparative_tables, steps=steps, sources=sources, write_to=write_to)
    if limitations_md:
        if '## 5. Primary Sources' in md:
            md = md.replace('## 5. Primary Sources', limitations_md + '\n\n---\n\n## 5. Primary Sources', 1)
        else:
            md = md.rstrip() + '\n\n---\n\n' + limitations_md + '\n'
        if write_to:
            from pathlib import Path as _P
            _P(write_to).write_text(md, encoding='utf-8')
    return md
if __name__ == '__main__':
    demo = {'pages_fetched': [{'title': 'Demo Source', 'url': 'https://example.com/article', 'text': 'First paragraph of a real article.\n\nStep 1: install the package with pip install demo-tool.\n\nStep 2: run demo-tool --init to create the config.', 'tables': [{'caption': 'Demo spec', 'rows': [['Field', 'Value'], ['latency', '10ms']]}], 'images': [{'src': 'https://example.com/diagram.png', 'alt': 'diagram'}], 'links': [{'href': 'https://example.com/docs', 'text': 'docs'}], 'code_blocks': [], 'videos': []}], 'findings': [{'text': 'Demo finding sentence for the brief.', 'source_domains': ['example.com'], 'source_urls': [], 'tier': 'unlisted', 'score': 2}], 'searches': []}
    md = publish_from_greyhound('Demo Guide', None, demo, write_to='/tmp/demo-guide.md')
    print(md[:1500])