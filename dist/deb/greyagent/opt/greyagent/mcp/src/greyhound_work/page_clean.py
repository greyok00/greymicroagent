from __future__ import annotations
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse
_COOKIE_LINE = re.compile('(?i)^\\s*(?:we use cookies?|this (?:website|site) uses cookies?|accept all cookies?|cookie (?:policy|notice|consent|settings)|manage (?:cookie )?preferences|your privacy choices|privacy & cookies)\\b[^\\n]{0,200}$')
_NEWSLETTER_LINE = re.compile('(?i)^\\s*(?:subscribe (?:to (?:our )?(?:newsletter|updates)|now)|sign up for (?:our )?newsletter|join our (?:newsletter|mailing list)|get (?:the latest|weekly) (?:news|updates) (?:in your inbox|by email)|your email address|enter your email)\\b[^\\n]{0,200}$')
_FOOTER_LINE = re.compile('(?i)^\\s*(?:©|\\(c\\)|copyright\\b|all rights reserved|powered by|terms of (?:use|service)|privacy policy|cookie policy|advertise with us|contact us|about us|careers|press|follow us(?: on)?|share this (?:article|page|post))[^\\n]{0,200}$')
_SOCIAL_LINE = re.compile('(?i)^\\s*(?:share (?:this|on)|tweet|pin it|share via|(?:facebook|twitter|x|linkedin|reddit|pinterest|whatsapp|telegram|instagram|youtube|tiktok)\\s*(?:share|follow|\\|))\\b[^\\n]{0,160}$')
_SKIP_TO = re.compile('(?i)^\\s*(?:skip|jump) to [a-z].{0,36}$|skip to (?:search|footer|content|main content|navigation)')
_NAV_LINE = re.compile('(?i)^\\s*(?:skip to (?:main )?content|skip to navigation|jump to (?:content|navigation|search)|back to top|main menu|open menu|close menu|toggle navigation|table of contents|on this page)\\b[^\\n]{0,160}$')
_RELATED_LINE = re.compile("(?i)^\\s*(?:related (?:articles?|posts?|reading|stories)|you may also like|recommended (?:for you|articles?|posts?)|trending now|most (?:read|popular)|editor'?s picks?|more (?:from|stories|articles?)|see also)\\b\\s*:?\\s*$")
_LOGIN_LINE = re.compile('(?i)^\\s*(?:sign in|log in|login|log on|create (?:free )?account|sign up|register|subscribe|get started|start free trial|buy now|add to cart|shop now|order now)\\b[^\\n]{0,160}$')
_TOGGLE_SUBSECTION = re.compile('(?i)^\\s*toggle\\b.*\\bsubsections?\\b')
_SALES_LINE = re.compile("(?i)\\b(?:get the report|book a (?:demo|call)|download now|start your free\\b|try (?:our|it) [\\w' -]{0,30}\\b(?:free|now)\\b|ready to (?:audit|protect|get|try)\\b)")
_NAVVERB_STUB = re.compile('(?i)^(?:why|about|jobs?|contact|products?|pricing|blog|open|check|get|book|try|download|learn|faqs?|support|services?|solutions?|resources?|company|careers|login|sign in|search|menu)\\b[^.?!:,;]{0,24}$')
_CREDIT_LINE = re.compile('(?i)(fotolia|getty images|istockphoto|shutterstock|alamy|dreamstime|depositphotos|adobe stock|123rf|bigstock|credit[s]?:)')
_BANNER_CTA_LINE = re.compile('(?i)\\b(?:wiki loves\\b|gagnez\\b|photographiez\\b|win (?:an|a|our) (?:award|prize|medal)\\b|make (?:a )?donation\\b|donate (?:today|now|monthly)\\b)')
_BREADCRUMB_LINE = re.compile('[^\\n>]{1,60} > [^\\n>]{1,60} > ')
_BETA_UPSELL = re.compile('(?i)\\bjoin (?:the|our) (?:beta|waitlist|program|list)\\b|\\bjoin us (?:on|for|in) (?:discord|slack|reddit|the beta)\\b|\\bearly access\\b.{0,40}\\bjoin\\b')
_EVENT_PROMO = re.compile('(?i)\\bis hitting the road\\b|\\bjoin us for (?:drinks|coffee|dinner|an evening|lunch)\\b|\\bfind your city\\b|\\bbook your (?:seat|spot|table)\\b|\\brsvp\\b')
_BOT_LINE = re.compile('(?i)(just a moment|checking your browser|please verify you are human|enable javascript|ddos protection by|attention required|access denied|you have been blocked|captcha)')
_NAV_GLUE_PREFIX = re.compile("(?i)^(?:(?:forums?|what's new|search forums?|new posts|members?|latest activity|search|menu|home|contact|faq|help|guest|announcements|unread posts?|log ?in|register|login)\\s+){2,}")
_GREETING_PREFIX = re.compile('(?i)^hello (?:guest|user|there|everyone)[.,!]?\\s*')
_FORUM_META = re.compile('(?i)\\battachments?:?\\s+\\S+\\.(?:zip|gz|log|txt|png|jpe?g)\\s*[-. ]?\\s*[\\d.]*\\s*[KMG]?B?\\b|(?:sort by (?:date|oldest|newest|votes|views|replies|title)\\s*){1,}|\\bviews?:\\s*[\\d,]+(?:\\s*[-/|]\\s*\\d+)?\\b|\\brepl(?:ies|y) count\\b:?\\s*[\\d,]+\\b|\\b\\d+\\s*(?:KB|MB|B)\\s*[-·.]\\s*views?:\\s*[\\d,]+|\\bjump to\\b\\s*$')

def _strip_forum_meta(text: str) -> str:
    return '\n'.join((_FORUM_META.sub(' ', ln) for ln in text.split('\n')))

def _strip_nav_glue(text: str) -> str:
    for _ in range(2):
        text = '\n'.join((_NAV_GLUE_PREFIX.sub('', ln) for ln in text.split('\n')))
        text = '\n'.join((_GREETING_PREFIX.sub('', ln) for ln in text.split('\n')))
        text = '\n'.join((re.sub('(?i)\\s*hello (?:guest|user|there|everyone)\\s*[.,!]?', ' ', ln) for ln in text.split('\n')))
        text = _strip_forum_meta(text)
    return text
_MENU_ITEM = re.compile("^[A-Za-z0-9][A-Za-z0-9 &/\\-'().,%]{1,60}$")
_META_DESC_RE = re.compile('<meta[^>]+(?:name|property)=[\\"\'](?:description|og:description|twitter:description)[\\"\'][^>]+content=[\\"\']([^\\"\']{0,500})[\\"\']', re.I | re.S)
_CANONICAL_RE = re.compile('<link[^>]+rel=[\\"\']canonical[\\"\'][^>]+href=[\\"\']([^\\"\']+)[\\"\']', re.I | re.S)
_H1_RE = re.compile('<h1[^>]*>(.*?)</h1>', re.I | re.S)
_H2_RE = re.compile('<h2[^>]*>(.*?)</h2>', re.I | re.S)
_TAG_RE = re.compile('<[^>]+>')
EXCERPT_MIN = 1500
EXCERPT_MAX = 2000
MIN_MAIN_CHARS = 800

def _strip_tags(html: str) -> str:
    return _TAG_RE.sub(' ', html or '')

def _norm_ws(text: str) -> str:
    text = re.sub('[ \\t]+', ' ', text or '')
    text = re.sub(' ?\\n ?', '\n', text)
    text = re.sub('\\n{3,}', '\n\n', text)
    return _strip_nav_glue(text.strip())

def _split_blocks(text: str) -> List[str]:
    return [b.strip() for b in re.split('\\n\\s*\\n', text or '') if b.strip()]

def _is_chrome_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if len(s) > 400:
        return False
    if len(s) < 200 and _SALES_LINE.search(s):
        return True
    if len(s) < 200 and _BANNER_CTA_LINE.search(s):
        return True
    if _BREADCRUMB_LINE.search(s):
        return True
    if len(s) < 200 and _BETA_UPSELL.search(s):
        return True
    if len(s) < 200 and _EVENT_PROMO.search(s):
        return True
    return bool(_COOKIE_LINE.match(s) or _NEWSLETTER_LINE.match(s) or _FOOTER_LINE.match(s) or _SOCIAL_LINE.match(s) or _NAV_LINE.match(s) or _SKIP_TO.search(s) or _CREDIT_LINE.search(s) or _RELATED_LINE.match(s) or _TOGGLE_SUBSECTION.match(s) or _LOGIN_LINE.match(s) or _BOT_LINE.search(s))

def _navverb_short(line: str) -> bool:
    s = (line or '').strip()
    if not 4 <= len(s) < 25:
        return False
    if re.search('[.?!:;,]', s):
        return False
    return bool(_NAVVERB_STUB.match(s))

def _drop_menu_runs(lines: List[str]) -> List[str]:
    out: List[str] = []
    i, n = (0, len(lines))
    while i < n:
        if _MENU_ITEM.match(lines[i].strip()) and (not re.search('\\b(is|are|was|were|the|and|of|to|with|how|what|why|for|in|on)\\b', lines[i], re.I)):
            j = i
            while j < n and _MENU_ITEM.match(lines[j].strip()) and (not re.search('\\b(is|are|was|were|the|and|of|to|with|how|what|why|for|in|on)\\b', lines[j], re.I)):
                j += 1
            if j - i >= 3:
                i = j
                continue
        if _navverb_short(lines[i]):
            j = i
            while j < n and _navverb_short(lines[j]):
                j += 1
            if j - i >= 2:
                i = j
                continue
        out.append(lines[i])
        i += 1
    return out

def _dedupe_blocks(blocks: List[str]) -> tuple[List[str], float]:
    if not blocks:
        return (blocks, 0.0)
    seen: set[str] = set()
    kept: List[str] = []
    dup_chars = 0
    for b in blocks:
        key = re.sub('\\s+', ' ', b).strip().lower()
        if len(key) >= 40 and key in seen:
            dup_chars += len(b)
            continue
        if len(key) >= 40:
            seen.add(key)
        kept.append(b)
    dup_ratio = dup_chars / max(sum((len(b) for b in blocks)), 1) if blocks else 0.0
    return (kept, min(dup_ratio, 1.0))

def _boilerplate_ratio(raw_text: str, kept_text: str) -> float:
    raw_len = len(raw_text or '')
    if raw_len <= 0:
        return 1.0
    removed = max(raw_len - len(kept_text), 0)
    return min(removed / raw_len, 1.0)

def _excerpt_of(body: str) -> str:
    body = (body or '').strip()
    if len(body) <= EXCERPT_MAX:
        return body
    cut = body[:EXCERPT_MAX]
    para = cut.rfind('\n\n')
    if para > EXCERPT_MIN:
        cut = cut[:para]
    elif cut.rfind('. ') > EXCERPT_MIN:
        cut = cut[:cut.rfind('. ') + 1]
    return cut.strip()

def _img_context(text: str, src: str, window: int=600) -> str:
    if not text:
        return ''
    blocks = _split_blocks(text)
    ctx: List[str] = []
    for i, b in enumerate(blocks):
        if src and src in b:
            continue
        stem = re.sub('[^a-z0-9]+', ' ', (urlparse(src).path.rsplit('/', 1)[-1] if src else '').lower()).strip()
        if stem and len(stem) >= 6 and (stem in b.lower()):
            ctx.append(b[:window])
    if ctx:
        return ' '.join(ctx)[:window]
    for b in blocks:
        if len(b) > 120:
            return b[:window]
    return ''

def clean_page(scrape: Dict[str, Any]) -> Dict[str, Any]:
    raw_text = scrape.get('raw_text') or scrape.get('text') or ''
    text = scrape.get('text') or raw_text
    html = scrape.get('html') or ''
    metadata = scrape.get('metadata') or {}
    lines = text.split('\n')
    kept_lines = [ln for ln in lines if not _is_chrome_line(ln)]
    kept_lines = _drop_menu_runs(kept_lines)
    text = _norm_ws('\n'.join(kept_lines))
    blocks = _split_blocks(text)
    blocks, dup_ratio = _dedupe_blocks(blocks)
    body = _norm_ws('\n\n'.join(blocks))
    bp_ratio = max(_boilerplate_ratio(raw_text, body), dup_ratio if blocks else 0.0)
    final_url = scrape.get('final_url') or scrape.get('url') or ''
    canonical = final_url
    if html:
        m = _CANONICAL_RE.search(html[:200000])
        if m:
            canonical = urljoin(final_url, m.group(1))
    if canonical:
        p = urlparse(canonical)
        canonical = f'{p.scheme}://{p.netloc}{p.path}'.rstrip('/') or canonical
    title = (scrape.get('title') or '').strip()
    meta_desc = ''
    if html:
        m = _META_DESC_RE.search(html[:200000])
        if m:
            meta_desc = _strip_tags(m.group(1)).strip()
    if not meta_desc and isinstance(metadata, dict):
        meta_desc = str(metadata.get('description') or '').strip()
    h1 = ''
    h2s: List[str] = []
    scraped_headings = scrape.get('headings') or []
    if scraped_headings:
        for h in scraped_headings:
            lvl = (h.get('level') or '').upper()
            t = (h.get('text') or '').strip()
            if not t:
                continue
            if lvl == 'H1' and (not h1):
                h1 = t
            elif lvl == 'H2':
                h2s.append(t)
    if not h1 and html:
        m = _H1_RE.search(html[:200000])
        if m:
            h1 = _norm_ws(_strip_tags(m.group(1)))
    if not h1:
        h1 = title
    if not h2s and html:
        h2s = [_norm_ws(_strip_tags(m.group(1))) for m in list(_H2_RE.finditer(html[:200000]))[:20]]
        h2s = [h for h in h2s if h]
    images_out: List[Dict[str, Any]] = []
    for img in scrape.get('images') or []:
        src = (img.get('src') or '').strip()
        if not src.startswith('http'):
            continue
        alt = (img.get('alt') or '').strip()
        cap = (img.get('caption') or img.get('title') or '').strip()
        images_out.append({'src': src, 'alt': alt, 'caption': cap, 'context': _img_context(body, src), 'w': img.get('w', 0) or 0, 'h': img.get('h', 0) or 0})
    return {'canonical_url': canonical, 'url': scrape.get('url') or final_url, 'final_url': final_url, 'title': title, 'meta_description': meta_desc, 'h1': h1, 'h2s': h2s[:20], 'body_text': body, 'excerpt': _excerpt_of(body), 'boilerplate_ratio': round(bp_ratio, 3), 'duplicate_ratio': round(dup_ratio, 3), 'images': images_out, 'n_links': len(scrape.get('links') or []), 'n_tables': len(scrape.get('tables') or []), 'main_chars': len(body)}

def is_thin(cleaned: Dict[str, Any], min_chars: int=MIN_MAIN_CHARS) -> bool:
    return int(cleaned.get('main_chars') or 0) < min_chars
if __name__ == '__main__':
    import json as _json
    import sys as _sys
    demo = {'url': 'https://example.com/post?a=1#frag', 'final_url': 'https://example.com/post?a=1', 'title': 'Demo Page', 'text': 'We use cookies to improve your experience. Accept all cookies.\nHome\nProducts\nPricing\nAbout\nContact\nSkip to content\nThis is the first real paragraph of the article and it is long enough to count as main content for the cleaner.\n\nThis is the second paragraph with the actual teaching material.\n\n© 2026 Example Corp. All rights reserved.\nSubscribe to our newsletter\nFollow us on Twitter', 'raw_text': '', 'html': '<html><head><meta name="description" content="A demo page"><link rel="canonical" href="https://example.com/post"></head><body><h1>Demo Page</h1></body></html>', 'headings': [{'level': 'H1', 'text': 'Demo Page'}], 'images': [{'src': 'https://example.com/diagram.png', 'alt': 'diagram', 'w': 800, 'h': 400}], 'links': [], 'tables': [], 'metadata': {}}
    demo['raw_text'] = demo['text']
    print(_json.dumps(clean_page(demo), indent=2)[:1800])