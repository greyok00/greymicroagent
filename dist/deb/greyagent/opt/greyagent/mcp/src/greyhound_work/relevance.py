from __future__ import annotations
import json
import re
import subprocess
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urlparse
JUDGE_BATCH = 1
JUDGE_EXCERPT_CHARS = 4000
ACCEPT_SCORE = 75
QUARARANTINE_SCORE = 55
PRIMARY_SOURCE_MIN_SCORE = 50
CANONICAL_SOURCE_MIN_SCORE = 0
PRIMARY_SOURCE_EXCEPTION_REASON = 'primary source exception: official/reference material that matches the scope'
_BAD_URL_PATH = re.compile('(?i)(^|/)(search|results|tag|tags|category|categories|author|authors|feed|feeds|rss|atom|amp|print|login|signin|signup|register|checkout|cart|account|wp-admin|wp-login|admin|search\\.php|index\\.php)(/|$|\\?|#)')
_BAD_URL_QUERY = re.compile('(?i)[?&](page|paged|offset|sort|filter|s|search|q|query)=')
_HOMEPAGE_PATH = re.compile('^/[a-z]{0,2}(-[a-z]{2})?/?$')
_AFFILIATE_TITLE = re.compile('(?i)\\b(top\\s+\\d+|best\\s+\\d+|\\d+\\s+best|\\d+\\s+top|reviewed and compared|we tested|our (?:top )?picks|buying guide|\\d+\\s+(?:best|top)\\b|affiliate|roundup|listicle)\\b')
_DICTIONARY_TITLE = re.compile('(?i)\\b(definition of|meaning of|what does .* mean|synonyms? for|translate \\w+ to|how to pronounce)\\b')
_AFFILIATE_HOSTS = re.compile('(?i)(?:^|\\.)(?:affiliate|affiliates|partners?|bestreviews|top10|top-ten|listverse|coupons?|deals?|best-deals?|top-\\d+)\\.(?:com|net|org|io|co)\\b')
_SOURCE_TYPE_BY_TIER = {'primary': 'official_docs', 'secondary': 'technical_reference', 'unlisted': 'unknown'}
_SOURCE_TYPE_BY_DOMAIN = re.compile('(?i)(?:^|\\.)(?:docs?\\.|developer\\.|learn\\.|support\\.|help\\.|aka\\.ms|microsoft\\.com|apple\\.com|mozilla\\.org|ietf\\.org|nist\\.gov|cisa\\.gov|fbi\\.gov|sec\\.gov|gov|mitre\\.org|arxiv\\.org|acm\\.org|ieee\\.org|w3\\.org|owasp\\.org|sans\\.org|us-cert\\.circl\\.lu|github\\.com|gitlab\\.com|stackoverflow\\.com|en\\.wikipedia\\.org|first\\.org|cisa\\.gov|cisa)')
_SOURCE_TYPE_NEWS = re.compile('(?i)(?:^|\\.)(?:reuters|apnews|ap\\.org|bbc|npr|theguardian|nytimes|washingtonpost|bloomberg|ft\\.com|wsj|arstechnica|theregister|techcrunch|theverge|wired|bleepingcomputer|crowdstrike|sentinelone|mandiant|unit42|recordedfuture|mandiant|eset|kaspersky|symantec|malwarebytes|trendmicro|virustotal|abuse\\.ch|cisa\\.gov)')
_OFFICIAL_DOC_PREFIX = re.compile('(?i)^(?:docs?|developer|learn|support|help)\\.')
_PRIMARY_SOURCE_DOMAINS = re.compile('(?i)(?:^|\\.)(?:mitre\\.org|attack\\.mitre\\.org|learn\\.microsoft\\.com|docs\\.microsoft\\.com|man7\\.org|apple\\.com|developer\\.apple\\.com|nist\\.gov|nvd\\.nist\\.gov|cisa\\.gov|volatilityfoundation\\.org|yara\\.readthedocs\\.io|capev2\\.readthedocs\\.io|readthedocs\\.io|ietf\\.org|rfc-editor\\.org|w3\\.org|kernel\\.org|docs\\.kernel\\.org|gnu\\.org|owasp\\.org|first\\.org|docs\\.python\\.org|developer\\.mozilla\\.org)\\b')
_PROCEDURAL_TITLE = re.compile('(?i)\\b(how to|guide|tutorial|walkthrough|step[- ]by[- ]step|getting started|setup|install|configure|deploy|checklist|playbook|runbook|reference|docs?|documentation|manual|handbook|explained|101|fundamentals|basics)\\b')
_TIME_WORDS = re.compile('(?i)\\b(202[4-9]|latest|recent|current|newest|today|this (?:week|month|year)|breaking|update[sd]? (?:in|as of)|2025|2026)\\b')
_STOPWORDS = {'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'any', 'can', 'her', 'was', 'one', 'our', 'out', 'day', 'get', 'has', 'him', 'his', 'how', 'its', 'may', 'new', 'now', 'old', 'see', 'two', 'way', 'who', 'with', 'from', 'that', 'this', 'what', 'when', 'your', 'than', 'then', 'into', 'over', 'such', 'use', 'used', 'using', 'via', 'per'}
ACRONYM_EXPANSIONS = {'waf': 'firewall web application firewall', 'vpn': 'vpn private network', 'ngfw': 'next generation firewall', 'utm': 'unified threat management', 'siem': 'security information event management', 'edr': 'endpoint detection response', 'xdr': 'extended detection response', 'mfa': 'multi factor authentication', 'sso': 'single sign on', 'rbac': 'role based access control', 'dmz': 'demilitarized zone network', 'ids': 'intrusion detection', 'ips': 'intrusion prevention', 'ct': 'certificate transparency', 'xss': 'cross site scripting', 'csrf': 'cross site request forgery', 'iot': 'internet of things', 'llm': 'large language model', 'vm': 'virtual machine', 'os': 'operating system', 'ssrf': 'server side request forgery', 'acl': 'access control list'}

def _stem(tok: str) -> str:
    t = tok
    if len(t) > 4 and t.endswith('ies'):
        return t[:-3] + 'y'
    if len(t) > 3 and t.endswith('s') and (not t.endswith('ss')):
        return t[:-1]
    return t

def question_tokens(question: str) -> set:
    raw = [_stem(t) for t in re.split('[^a-z0-9]+', (question or '').lower()) if len(t) > 2 and t not in _STOPWORDS]
    out = set(raw)
    for t in raw:
        exp = ACRONYM_EXPANSIONS.get(t)
        if exp:
            out |= {_stem(w) for w in exp.split()}
    return out

def _domain(url: str) -> str:
    try:
        d = urlparse(url or '').netloc.lower()
        return d[4:] if d.startswith('www.') else d
    except Exception:
        return ''

def token_coverage(text: str, tokens: set) -> float:
    if not tokens:
        return 1.0
    hay = (text or '').lower()
    hay_words = {_stem(w) for w in re.findall('[a-z0-9]+', hay)}
    return sum((1 for t in tokens if _stem(t) in hay_words)) / len(tokens)

def prefilter(url: str, title: str='', snippet: str='', domain: str='', tier: str='', tokens: Optional[set]=None, question: str='') -> Dict[str, Any]:
    tokens = tokens if tokens is not None else question_tokens(question)
    dom = domain or _domain(url)
    path = urlparse(url or '').path or '/'
    title = title or ''
    decision, reason = ('accept', '')
    coverage = token_coverage(' '.join([title, url, snippet]), tokens)
    if _AFFILIATE_HOSTS.search(dom or ''):
        return {'decision': 'reject', 'reason': 'affiliate/coupon host', 'coverage': coverage, 'procedural': False, 'tier': tier}
    if _BAD_URL_PATH.search(path) or _BAD_URL_QUERY.search(url or ''):
        return {'decision': 'reject', 'reason': 'search/tag/category/feed/pagination URL', 'coverage': coverage, 'procedural': False, 'tier': tier}
    if _HOMEPAGE_PATH.match(path) and (not _PROCEDURAL_TITLE.search(title)):
        return {'decision': 'reject', 'reason': 'homepage (no article signal)', 'coverage': coverage, 'procedural': False, 'tier': tier}
    if _DICTIONARY_TITLE.search(title):
        return {'decision': 'reject', 'reason': 'dictionary/definition page', 'coverage': coverage, 'procedural': False, 'tier': tier}
    if _AFFILIATE_TITLE.search(title) and coverage < 0.5:
        return {'decision': 'reject', 'reason': 'affiliate/listicle title with weak topic coverage', 'coverage': coverage, 'procedural': False, 'tier': tier}
    if tokens and coverage < 0.34:
        return {'decision': 'reject', 'reason': f'low topic-token coverage ({coverage:.0%})', 'coverage': coverage, 'procedural': False, 'tier': tier}
    procedural = bool(_PROCEDURAL_TITLE.search(title))
    if coverage < 0.6:
        decision, reason = ('deprioritize', 'partial topic coverage')
    return {'decision': decision, 'reason': reason, 'coverage': coverage, 'procedural': procedural, 'tier': tier}

def _debug_last_judge(text: str) -> None:
    _JUDGE_DEBUG.append(text)
    del _JUDGE_DEBUG[:-4]
_JUDGE_DEBUG: List[str] = []

def last_judge_replies() -> List[str]:
    return list(_JUDGE_DEBUG)
_FENCE_ARR_RE = re.compile('```(?:json)?\\s*(\\[.*?\\])\\s*```', re.S)
_FENCE_OBJ_RE = re.compile('```(?:json)?\\s*(\\{.*?\\})\\s*```', re.S)
_PAGE_OBJ_RE = re.compile('\\{\\s*\\"page\\"\\s*:\\s*\\d+.*?\\n\\s*\\}', re.S)
_OBJ_SHAPE_RE = re.compile('\\{[^{}]*\\"page\\"[^{}]*\\"(?:decision|relevance_score)\\"[^{}]*\\}', re.S)

def _normalize_decision(obj: Optional[Dict[str, Any]], fallback_reason: str) -> Dict[str, Any]:
    base = {'decision': 'quarantine', 'relevance_score': 50, 'source_type': 'unknown', 'reason': fallback_reason, 'allowed_content': [], 'risk_flags': []}
    if not isinstance(obj, dict):
        return base
    decision = str(obj.get('decision', '')).strip().lower()
    if decision not in ('accept', 'quarantine', 'reject'):
        decision = 'quarantine'
    try:
        score = int(obj.get('relevance_score', 50))
    except Exception:
        score = 50
    score = max(0, min(100, score))
    if score >= ACCEPT_SCORE:
        decision = 'accept'
    elif score < QUARARANTINE_SCORE:
        decision = 'reject'
    else:
        decision = 'quarantine'
    st = str(obj.get('source_type', 'unknown')).strip().lower()
    if st not in ('official_docs', 'primary_source', 'technical_reference', 'news', 'commercial', 'forum', 'unknown'):
        st = 'unknown'
    allowed = obj.get('allowed_content')
    if not isinstance(allowed, list):
        allowed = []
    allowed = [str(a) for a in allowed if str(a) in ('procedures', 'specifications', 'background', 'images')]
    flags = obj.get('risk_flags')
    if not isinstance(flags, list):
        flags = []
    flags = [str(f) for f in flags if str(f) in ('boilerplate', 'off_topic', 'thin_content', 'sales_copy', 'outdated', 'unsupported', 'commit_log')]
    return {'decision': decision, 'relevance_score': score, 'source_type': st, 'reason': str(obj.get('reason', fallback_reason))[:300] or fallback_reason, 'allowed_content': allowed, 'risk_flags': flags}
_GENERIC_ENTITY_TERMS = frozenset({'compromise', 'compromised'})

def contamination_check(page: Dict[str, Any], required_entities: Sequence[Sequence[str]]) -> Dict[str, Any]:
    title_text = ' '.join([page.get('title') or '', page.get('canonical_url') or page.get('url') or '', ' '.join(page.get('h2s') or [])]).lower()
    focused_text = title_text + ' ' + (page.get('excerpt') or '')[:2000].lower()
    body_text = (page.get('body_text') or '')[:6000].lower()
    matched: List[str] = []
    for group in required_entities:
        terms = [str(term) for term in group if str(term).strip()]
        non_generic = [term for term in terms if term.lower() not in _GENERIC_ENTITY_TERMS]
        hit = next((term for term in non_generic if term.lower() in focused_text), None)
        if hit is None:
            hit = next((term for term in terms if term.lower() in _GENERIC_ENTITY_TERMS and term.lower() in title_text), None)
        if hit is None:
            hit = next((term for term in non_generic if body_text.count(term.lower()) >= 2), None)
        if hit is None:
            present = [term for term in non_generic if body_text.count(term.lower()) >= 1]
            if len(present) >= 2:
                hit = present[0]
        if hit is None:
            return {'clean': False, 'matched': matched, 'reason': 'missing required entity: ' + '/'.join(terms)}
        matched.append(hit)
    return {'clean': True, 'matched': matched, 'reason': 'all entity groups matched'}
_NOISE_LINE_RE = re.compile('(?i)^(?:\\d{4}-\\d{2}-\\d{2}\\s*)?(?:[0-9a-f]{7,40}\\b|merge (?:pull request|branch|remote)\\b|jump up to:|we use cookies|accept(?: all)? cookies?|manage cookies?|cookie (?:policy|settings|notice|preferences)|\\b(?:bump|chore|feat|fix|refactor|revert|test|build|ci|docs|perf)(?:[:(]|\\s))')
NOISE_RATIO_FLOOR = 0.4
NOISE_MIN_LINES = 8

def noise_line_ratio(text: str) -> float:
    lines = [ln.strip() for ln in (text or '').splitlines() if ln.strip()]
    if not lines:
        return 0.0
    hits = sum((1 for ln in lines if _NOISE_LINE_RE.match(ln)))
    return hits / len(lines)

def noise_shape_warnings(page: Dict[str, Any]) -> List[str]:
    body = page.get('body_text') or page.get('excerpt') or ''
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    if len(lines) < NOISE_MIN_LINES:
        return []
    ratio = noise_line_ratio(body)
    if ratio < NOISE_RATIO_FLOOR:
        return []
    return [f'commit-log noise: {ratio:.0%} of body lines are commit-log / cookie-banner / citation debris, not article prose — text quality is thin relative to its size']

def ordered_question_tokens(question: str) -> List[str]:
    out: List[str] = []
    for t in re.split('[^a-z0-9]+', (question or '').lower()):
        t = t.strip()
        if t and len(t) > 2 and (t not in _STOPWORDS) and (t not in out):
            out.append(t)
    return out

def focal_tail_drift(question: str, page: Dict[str, Any]) -> Optional[str]:
    ordered = ordered_question_tokens(question)
    if len(ordered) < 2:
        return None
    hay = ' '.join([page.get('title') or '', page.get('canonical_url') or page.get('url') or '', ' '.join((str(h) for h in page.get('h2s') or [])), (page.get('body_text') or page.get('excerpt') or '')[:12000]]).lower()
    hay_words = {_stem(w) for w in re.findall('[a-z0-9]+', hay)}
    if _stem(ordered[-1]) in hay_words:
        return None
    covered = [t for t in ordered[:-1] if _stem(t) in hay_words]
    if not covered:
        return None
    missing = [t for t in ordered if _stem(t) not in hay_words]
    return f"off-topic drift: the question's focal tail term(s) {', '.join(missing)} never appear while the broader head terms ({', '.join(covered)}) do — the page answers the head of the question, not the subject itself"

def classify_source_type(domain: str, tier: str, title: str='') -> str:
    if tier == 'primary' or tier == 'official':
        return 'official_docs'
    if _SOURCE_TYPE_BY_DOMAIN.search(domain or ''):
        return 'technical_reference'
    if _SOURCE_TYPE_NEWS.search(domain or ''):
        return 'news'
    if tier == 'secondary':
        return 'technical_reference'
    return 'unknown'

def _deterministic_official_domain(page: Dict[str, Any]) -> bool:
    dom = _domain(page.get('canonical_url') or page.get('url') or '')
    if _PRIMARY_SOURCE_DOMAINS.search(dom):
        return True
    if _OFFICIAL_DOC_PREFIX.search(dom):
        return True
    hint = classify_source_type(dom, str(page.get('tier') or ''), page.get('title') or '')
    return hint in ('official_docs', 'primary_source')

def _is_primary_reference_source(page: Dict[str, Any], source_type: str='') -> bool:
    st = (source_type or '').strip().lower()
    if st in ('news', 'commercial', 'forum'):
        return False
    return _deterministic_official_domain(page)

def _canonical_source_floor(page: Dict[str, Any], source_type: str='') -> int:
    if _deterministic_official_domain(page):
        return CANONICAL_SOURCE_MIN_SCORE
    return PRIMARY_SOURCE_MIN_SCORE

def _page_is_thin(page: Dict[str, Any]) -> bool:
    body = (page.get('body_text') or page.get('excerpt') or '').strip()
    return len(body) < 800

def _is_marketing_or_listicle(page: Dict[str, Any], source_type: str='', risk_flags: Optional[Sequence[str]]=None) -> bool:
    st = (source_type or '').strip().lower()
    if st in ('news', 'commercial'):
        return True
    if 'sales_copy' in {str(f) for f in risk_flags or []}:
        return True
    title = page.get('title') or ''
    if _AFFILIATE_TITLE.search(title) or _DICTIONARY_TITLE.search(title):
        return True
    dom = _domain(page.get('canonical_url') or page.get('url') or '')
    return classify_source_type(dom, str(page.get('tier') or ''), title) == 'news'

def _deterministic_judge_obj(question: str, page: Dict[str, Any], guide_type: str='research guide', scope: str='', expected_source_types: Optional[Sequence[str]]=None) -> Dict[str, Any]:
    title = (page.get('title') or '').lower()
    body = ((page.get('body_text') or page.get('excerpt') or '') or '').lower()
    head = ' '.join((h or '' for h in page.get('h2s') or [])).lower()
    dom = _domain(page.get('url') or '')
    st = classify_source_type(dom, str(page.get('tier') or ''), page.get('title') or '')
    toks = question_tokens(question)
    scope_tok = question_tokens(scope) if (scope or '').strip() else set()
    window = body[:12000]
    cov_t = token_coverage(title, toks) if toks else 0.0
    cov_h = token_coverage(head, toks) if toks else 0.0
    cov_b = token_coverage(window, toks) if toks else 0.0
    cov_s = token_coverage(window, scope_tok) if scope_tok else 0.0
    score = 50.0 + 40.0 * cov_t + 8.0 * cov_h + 15.0 * cov_b + 7.0 * cov_s
    if cov_b >= 0.6:
        score += 10.0
    score = min(100.0, score)
    reasons = [f'title coverage {cov_t:.2f}', f'body coverage {cov_b:.2f}', f'headings coverage {cov_h:.2f}']
    if not toks:
        reasons.append('no extractable question tokens — quarantine band')
    elif cov_t == 0.0 and cov_b == 0.0 and (cov_h == 0.0):
        score = 30.0
        reasons.append('zero coverage of question tokens — clear topic mismatch')
    if _page_is_thin(page):
        score -= 20.0
        reasons.append('thin page penalty')
    risks: List[str] = []
    if _is_marketing_or_listicle(page, st, risks):
        score = min(score, 54.0)
        reasons.append('marketing/listicle signal capped to quarantine band')
    score = int(max(0.0, min(100.0, score)))
    if score >= ACCEPT_SCORE:
        decision = 'accept'
    elif score >= QUARARANTINE_SCORE:
        decision = 'quarantine'
    else:
        decision = 'reject'
    return {'decision': decision, 'relevance_score': score, 'source_type': st, 'reason': '; '.join(reasons) + f' [deterministic judge — {guide_type}]'}

def judge_pages(question: str, pages: Sequence[Dict[str, Any]], guide_type: str='research guide', *, scope: str='', required_entities: Optional[Sequence[Sequence[str]]]=None, expected_source_types: Optional[Sequence[str]]=None) -> List[Dict[str, Any]]:
    decisions: List[Dict[str, Any]] = []
    pages = list(pages)
    if required_entities:
        required_entities = [list(g) for g in required_entities]
    if expected_source_types:
        expected_source_types = list(expected_source_types)
    scope_text = (scope or '').strip() or '(not specified — use the question)'
    entities_text = json.dumps([list(g) for g in required_entities], ensure_ascii=False) if required_entities else '(none)'
    source_types_text = ', '.join((str(s) for s in expected_source_types)) if expected_source_types else '(any relevant source)'
    for p in pages:
        obj = _deterministic_judge_obj(question, p, guide_type)
        d = _normalize_decision(obj, 'deterministic judge')
        if d['source_type'] == 'unknown':
            d['source_type'] = classify_source_type(_domain(p.get('url') or ''), str(p.get('tier') or ''), p.get('title') or '')
        if d.get('decision') in ('quarantine', 'reject') and _is_primary_reference_source(p, d.get('source_type')) and (int(d.get('relevance_score', 0)) >= _canonical_source_floor(p, d.get('source_type'))):
            cont = contamination_check(p, required_entities) if required_entities else {'clean': True, 'matched': [], 'reason': 'no required entities supplied'}
            if required_entities:
                d['contamination'] = cont
            if cont['clean'] and (not _page_is_thin(p)) and (not _is_marketing_or_listicle(p, d.get('source_type'), d.get('risk_flags'))):
                d['judge_score'] = int(d.get('relevance_score', 0))
                d['relevance_score'] = max(int(d.get('relevance_score', 0)), ACCEPT_SCORE)
                d['decision'] = 'accept'
                d['primary_source_exception'] = True
                d['reason'] = PRIMARY_SOURCE_EXCEPTION_REASON
        drift = focal_tail_drift(question, p)
        noise = noise_shape_warnings(p)
        if drift:
            d['focal_tail_drift'] = drift
        if drift or noise:
            warnings = ([drift] if drift else []) + list(noise)
            d['quality_warnings'] = warnings
            if d.get('decision') == 'accept':
                d['decision'] = 'quarantine'
                d['relevance_score'] = min(int(d.get('relevance_score', 50)), QUARARANTINE_SCORE - 1)
                d.pop('primary_source_exception', None)
                flags = list(d.get('risk_flags') or [])
                for f in (['off_topic'] if drift else []) + (['commit_log'] if noise else []):
                    if f not in flags:
                        flags.append(f)
                d['risk_flags'] = flags
                d['reason'] = (warnings[0] + ' | ' + str(d.get('reason') or ''))[:300]
        if d.get('decision') == 'accept' and required_entities:
            cont = d.get('contamination') or contamination_check(p, required_entities)
            d['contamination'] = cont
            if not cont['clean']:
                d['decision'] = 'quarantine'
                d['relevance_score'] = min(int(d.get('relevance_score', 50)), 54)
                d['reason'] = cont['reason']
                d.pop('primary_source_exception', None)
        decisions.append(d)
    return decisions

def judge_available() -> bool:
    return True
_TIER_ORDER = {'primary': 0, 'official': 0, 'secondary': 1, 'unlisted': 2, 'excluded': 3}
_OFFICIAL_TYPES = {'official_docs', 'primary_source'}

def rank_results(question: str, results: Sequence[Dict[str, Any]], judged: Optional[Dict[str, Dict[str, Any]]]=None, freshness_matters: Optional[bool]=None) -> List[Dict[str, Any]]:
    judged = judged or {}
    tokens = question_tokens(question)
    if freshness_matters is None:
        freshness_matters = bool(_TIME_WORDS.search(question or ''))
    domain_seen: Dict[str, int] = {}

    def key(r: Dict[str, Any]) -> tuple:
        url = r.get('url') or ''
        dom = _domain(url)
        j = judged.get(url) or judged.get(r.get('canonical_url') or '') or {}
        score = j.get('relevance_score')
        if score is None:
            score = int(round(float(r.get('coverage', 0.5)) * 100))
        tier = str(r.get('tier') or 'unlisted')
        stype = str(j.get('source_type') or r.get('source_type') or '')
        procedural = bool(r.get('procedural') or _PROCEDURAL_TITLE.search(r.get('title') or ''))
        official = 1 if tier in ('primary', 'official') or stype in _OFFICIAL_TYPES else 0
        fresh = 1 if freshness_matters and _TIME_WORDS.search(' '.join([r.get('title') or '', r.get('snippet') or ''])) else 0
        dup_penalty = domain_seen.get(dom, 0)
        domain_seen[dom] = dup_penalty + 1
        return (-score, _TIER_ORDER.get(tier, 2), -official, -procedural, -fresh, dup_penalty)
    return sorted(list(results), key=key)
_JUNK_IMG_WORDS = re.compile('(?i)(logo|icon|avatar|badge|banner|button|sprite|favicon|placeholder|spacer|pixel|tracking|advertisement|\\bad\\b|adsense|hero image|stock photo|stock image|decorative|divider|separator|arrow|bullet|social|share|follow|comment|placeholder|loading|spinner|thumbnail|profile photo|author photo|team member|generic|unsplash|pexels|shutterstock|getty|freepik|lorem|sample|default|cover image|background image|illustration)')
_DIAGRAM_WORDS = re.compile('(?i)(diagram|flowchart|flow chart|architecture|schematic|wiring|circuit|blueprint|wireframe|mockup|screenshot|screen shot|figure|fig\\.?\\s*\\d|chart|graph|plot|timeline|infographic|setup|install|dashboard|control panel|terminal|cli|ui|interface|step \\d|process|workflow|pipeline|data flow|network map|topology|anatomy|breakdown|comparison|matrix|table|screenshot)')
_STOCK_ALT = re.compile('(?i)^\\s*(?:image|img|photo|picture|pic|graphic|illustration|art|hero|banner|background|an?\\s+image\\s+of|photo of|a picture of)?\\s*$')
_JUNK_IMG_URL = re.compile('(?i)(/icons?/|/img/icons/|_1px\\.|favicon|sprite|placeholder|/buttons?/|/banners?/|loading|spinner|tracking|pixel\\.|1x1|/logos?/|/avatars?/|default[_-]?(image|img|avatar|profile|user|thumb)|gravatar|wp-content/uploads/\\d{4}/\\d{2}/(?:logo|icon|badge|button))')
STOCK_SRC_RE = re.compile('(?i)(adobestock|istockphoto|shutterstock|gettyimages|dreamstime|depositphotos|freepik|pexels|unsplash|_next/image|hero[_/-]|heroimage)')
AD_NETWORK_RE = re.compile('(?i)(ad\\.gt|pubmatic|doubleclick|googlesyndication|adsystem|taboola|outbrain|criteo|scorecardresearch)')

def gate_image(image: Dict[str, Any], section_text: str='', section_heading: str='', page_accepted: bool=True) -> Dict[str, Any]:
    if not page_accepted:
        return {'keep': False, 'reason': 'page not accepted'}
    src = image.get('src') or ''
    alt = (image.get('alt') or '').strip()
    caption = (image.get('caption') or '').strip()
    context = (image.get('context') or '').strip()
    if STOCK_SRC_RE.search(src):
        return {'keep': False, 'reason': 'stock/hero image'}
    if AD_NETWORK_RE.search(src):
        return {'keep': False, 'reason': 'ad-network pixel'}
    if len(alt.split()) < 3 and (not _DIAGRAM_WORDS.search(alt)):
        return {'keep': False, 'reason': 'alt too short to verify topicality'}
    if _JUNK_IMG_URL.search(src):
        return {'keep': False, 'reason': 'chrome/asset URL pattern'}
    if _JUNK_IMG_WORDS.search(alt) or _JUNK_IMG_WORDS.search(caption):
        if not _DIAGRAM_WORDS.search(alt + ' ' + caption):
            return {'keep': False, 'reason': 'junk alt/caption (logo/stock/ad)'}
    if _STOCK_ALT.match(alt) and (not caption) and (not _DIAGRAM_WORDS.search(src)):
        return {'keep': False, 'reason': 'generic stock alt, no context'}
    objective = ' '.join([section_heading or '', section_text or '']).lower()
    tokens = question_tokens(objective) if objective.strip() else set()
    probe = ' '.join([alt, caption, context]).lower()
    if _DIAGRAM_WORDS.search(probe) or _DIAGRAM_WORDS.search(src.lower()):
        return {'keep': True, 'reason': 'diagram/screenshot supports an action'}
    if tokens:
        probe_tokens = question_tokens(probe)
        overlap = len(tokens & probe_tokens)
        if overlap >= 2 or (overlap >= 1 and len(probe_tokens) <= 3):
            return {'keep': True, 'reason': f'alt/context overlaps section ({overlap} tokens)'}
        if _JUNK_IMG_WORDS.search(probe):
            return {'keep': False, 'reason': 'no section overlap + chrome-ish context'}
        return {'keep': False, 'reason': 'alt/context does not overlap the section'}
    return {'keep': bool(_DIAGRAM_WORDS.search(probe)), 'reason': 'no section context; diagram-only'}
if __name__ == '__main__':
    import sys as _sys
    q = 'ransomware negotiation playbook double extortion'
    toks = question_tokens(q)
    print('tokens:', sorted(toks))
    for url, title in [('https://example.com/tag/ransomware', 'Ransomware - Tags'), ('https://docs.example.com/negotiate-playbook', 'Negotiation playbook guide'), ('https://dict.example.com/ransomware', 'Definition of ransomware'), ('https://spam.example.com/best-10-vpn-top-5', 'Top 10 best VPN deals 2026')]:
        print(url, '->', prefilter(url, title, '', question=q, tokens=toks))
    img = {'src': 'https://example.com/fig2-timeline.png', 'alt': 'Figure 2: attack timeline', 'caption': '', 'context': 'ransomware negotiation timeline steps'}
    print('image:', gate_image(img, section_heading='Ransomware negotiation', section_text='negotiation playbook double extortion'))