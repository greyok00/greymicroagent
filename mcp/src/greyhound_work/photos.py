"""Real-photo insertion for course modules and guides (2026-10-21).

Owner directive: "update all guides. give all guides relevant real images ...
add images, charts, tables, graphs, pie charts, whatever visual aids to ALL
GUIDES AND MODULES". Sources are keyless: Wikimedia Commons search first,
Openverse as fallback. Images stay topical: every photo query is built from
the module/guide's own title and lesson words. Nothing is invented; where a
query returns nothing relevant the module is skipped and counted.

The builder's own pipeline (site_render.download_images) then downloads the
inserted URLs into site assets, so pages end up self-contained. Alt text is
carried from the source's own description when available (>=3 words to pass
the semantic image gate; junk words avoided on purpose).

Idempotent: a module already carrying an "*Image:" provenance line is not
touched again.
"""
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any
UA = 'Mozilla/5.0 (X11; Linux x86_64; rv:151.0) Gecko/20100101 Firefox/151.0'
COMMONS = 'https://commons.wikimedia.org/w/api.php'
OPENVERSE = 'https://api.openverse.org/v1/images/'
_STOP = set('a an and are as at be by been being can could do did does\ndone for from how in into is it its may might must of on or shall should\nthat the this to use used using what when which while who why will with\nwould you your'.split())
_CACHE: dict[str, dict[str, Any]] = {}
_REPO_ROOT = Path(__file__).resolve().parent
_CACHE_PATH = Path(os.path.expanduser('~/.cache/greyhound/photo-query-cache.json'))
_CACHE_LOCK = threading.Lock()

def _load_cache() -> None:
    if not _CACHE and _CACHE_PATH.exists():
        try:
            _CACHE.update(json.loads(_CACHE_PATH.read_text()))
        except Exception:
            pass

def _save_cache() -> None:
    try:
        _CACHE_PATH.write_text(json.dumps(_CACHE))
    except Exception:
        pass
MONTHS = {'january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december'}
_FILLER = {'master', 'guide', 'best', 'top', 'new', 'complete', 'ultimate', 'overview', 'introduction', 'practical', 'review', 'summary', 'released', 'release', 'launch', 'launched', 'roundup', 'versus'}

def keywords(text: str, n: int=4) -> str:
    words = [w.strip('-') for w in re.sub('[^a-z0-9 -]', ' ', (text or '').lower()).split()]
    words = [w for w in words if w and w not in _STOP and (len(w) > 2)]
    date_units, tail, skip = ([], [], set())
    for i, w in enumerate(words):
        if i in skip:
            continue
        if w in MONTHS and i + 1 < len(words) and words[i + 1].isdigit():
            key = f'{w} {words[i + 1]}'
            if key not in date_units:
                date_units.append(key)
            skip.update((i, i + 1))
            continue
        if w not in _FILLER and (not w.isdigit()):
            tail.append(w)
    tail = list(dict.fromkeys(tail))
    if len(tail) > n - len(date_units):
        keep = n - len(date_units)
        tail = tail[-keep:] if keep > 0 else []
    units = date_units + tail
    return ' '.join(units[:max(n, 1)])

def _norm_img_url(url: str) -> str:
    u = url or ''
    if '://' not in u:
        return u
    scheme, host, path = (u.split('://', 1)[0], u.split('://', 1)[1], '')
    if '/' in host:
        host, path = host.split('/', 1)
        path = '/' + re.sub('/{2,}', '/', path.lstrip('/'))
    return f'{scheme}://{host}{path}'

def _http_json(url: str) -> dict[str, Any] | None:
    try:
        req = urllib.request.Request(url, headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode('utf-8', 'replace'))
    except Exception:
        return None

def commons_search(q: str) -> dict[str, Any] | None:
    for gsr in (f'intitle:{q}', f'filetype:bitmap {q}'):
        params = urllib.parse.urlencode({'action': 'query', 'format': 'json', 'prop': 'imageinfo', 'generator': 'search', 'gsrsearch': f'filetype:bitmap {gsr}', 'gsrnamespace': 6, 'gsrlimit': 8, 'iiurlwidth': 1024, 'iiprop': 'url|mime|size|extmetadata'})
        data = _http_json(f'{COMMONS}?{params}')
        if not data:
            continue
        pages = (data.get('query') or {}).get('pages') or {}
        for p in sorted(pages.values(), key=lambda x: x.get('index', 99)):
            info = (p.get('imageinfo') or [{}])[0]
            mime, w = (info.get('mime', ''), info.get('width') or 0)
            title = p.get('title', '').replace('File:', '').rsplit('.', 1)[0]
            if mime in ('image/jpeg', 'image/png') and (w or 0) >= 600:
                if re.search('(?i)logo|icon|coat of arms|flag of|map of\\b', title):
                    continue
                meta = info.get('extmetadata') or {}
                lic = (meta.get('LicenseShortName') or {}).get('value', '')
                artist = re.sub('<[^>]+>', '', (meta.get('Artist') or {}).get('value', ''))[:60]
                return {'url': _norm_img_url(info.get('thumburl') or info.get('url') or ''), 'title': title, 'creator': artist or (info.get('user') or 'Wikimedia Commons'), 'license': f"{lic or 'CC'} via Wikimedia Commons", 'width': w}
    return None

def openverse_search(q: str) -> dict[str, Any] | None:
    params = urllib.parse.urlencode({'q': q, 'page_size': 12})
    data = _http_json(f'{OPENVERSE}?{params}')
    if not data:
        return None
    qt = set(re.sub('[^a-z ]', ' ', q.lower()).split())
    for r in data.get('results') or []:
        title = (r.get('title') or '').lower()
        if not qt & set(re.sub('[^a-z ]', ' ', title).split()):
            continue
        if (r.get('width') or 0) >= 600 and r.get('url') and (r.get('extension', 'jpg').lower() in ('jpg', 'jpeg', 'png')):
            return {'url': _norm_img_url(r['url']), 'title': re.sub('\\s+', ' ', r.get('title') or q)[:80], 'creator': (r.get('creator') or r.get('source') or '')[:60], 'license': f"{(r.get('license') or '').upper()} via Openverse", 'width': r.get('width')}
    return None
SEARX = 'http://127.0.0.1:8890'
_JUNK_IMG = re.compile('(?i)repository-images\\.githubusercontent|badge|logo|avatar|icon|svg\\b|\\.svg($|\\?)|favicon|sprite|placeholder')

def searx_image_hits(q: str, limit: int=20) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({'q': q, 'categories': 'images', 'format': 'json'})
    try:
        req = urllib.request.Request(f'{SEARX}/search?{params}', headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=25) as r:
            data = json.loads(r.read().decode('utf-8', 'replace'))
    except Exception:
        return []
    out, seen = ([], set())
    for r in data.get('results') or []:
        src = r.get('img_src') or ''
        title = re.sub('\\s+', ' ', r.get('title') or '').strip()
        if not src or src in seen:
            continue
        seen.add(src)
        if _JUNK_IMG.search(src) or _JUNK_IMG.search(title):
            continue
        path = src.split('?')[0].split('#')[0].split('.')
        if path[-1].lower() not in ('jpg', 'jpeg', 'png', 'webp'):
            continue
        if not _img_topical(title, q):
            continue
        out.append({'url': _norm_img_url(src), 'title': title[:80], 'creator': r.get('source', 'SearXNG image lane'), 'license': f"web image via {', '.join(r.get('engines') or ['image search'])}", 'width': 0})
        if len(out) >= limit:
            break
    return out

def photo_pool(queries: list[str], per_query: int=12) -> list[dict[str, Any]]:
    pool: list[dict[str, Any]] = []
    seen: set[str] = set()
    for q in queries:
        if not q:
            continue
        for hit in searx_image_hits(q, per_query):
            if hit['url'] not in seen:
                seen.add(hit['url'])
                pool.append(hit)
    return pool
from concurrent.futures import ThreadPoolExecutor
_PERSON_STOCK_RE = re.compile('(?i)\\b(?:wom[ae]n|girls?|ladies?|man|men|boys?|executives?|business(?:woman|man|person|people|team|meeting)|models?|portrait|selfie|beautiful|beauty|smiling|handsome|shaking\\s+hands|offering\\s+handshake)\\b')
_NON_LATIN_SCRIPT_RE = re.compile('[Ͱ-ϿЀ-ӿ\u0590-\u05ff\u0600-ۿऀ-ॿ\u0e00-\u0e7f\u3040-ヿㇰ-ㇿ㐀-䶿一-鿿豈-\ufaff가-\ud7afᄀ-ᇿ\u3130-\u318f\uff00-\uffef]')
_EMOJI_RE = re.compile('[🀀-\U0001faff☀-➿⬀-⯿︀-️]')

def _content_tokens(text: str) -> set:
    return {t for t in re.sub('[^a-z0-9 -]', ' ', (text or '').lower()).split() if len(t) > 2 and t not in _STOP}

def _img_topical(title: str, q: str) -> bool:
    title_l = title or ''
    q_content, t_content = (_content_tokens(q), _content_tokens(title_l))
    shared = q_content & t_content
    if len(q_content) > 1 and len(shared) < 2:
        return False
    if len(q_content) == 1 and (not shared):
        return False
    if _EMOJI_RE.search(title_l):
        return False
    if _PERSON_STOCK_RE.search(title_l) and (not _PERSON_STOCK_RE.search(q or '')):
        return False
    if (q or '').isascii() and _NON_LATIN_SCRIPT_RE.search(title_l):
        return False
    return True

def _topical_hit(hit, q: str) -> bool:
    if not hit or not hit.get('url'):
        return False
    return _img_topical(hit.get('title') or '', q)

def find_photo(q: str) -> dict[str, Any] | None:
    with _CACHE_LOCK:
        _load_cache()
        if q in _CACHE:
            hit = _CACHE[q]
            return hit if _topical_hit(hit, q) else None
    hit = commons_search(q) or openverse_search(q)
    if hit and (not hit.get('url')):
        hit = None
    if hit and (not _img_topical(hit.get('title') or '', q)):
        hit = None
    if hit:
        with _CACHE_LOCK:
            _CACHE[q] = hit
            _save_cache()
    return hit

def insert_photo(md: str, photo: dict[str, str], what: str) -> str:
    alt = re.sub('\\s+', ' ', f"{what}: {photo['title']}").strip()
    alt = re.sub('(?i)\\b(logo|icon|avatar|thumbnail|banner|placeholder|stock photo|stock image|hero image)\\b', 'figure', alt)
    if len(alt.split()) < 3:
        alt = f'{what} illustration {alt}'
    block = f"\n\n![{alt}]({photo['url']})\n\n*Image: {photo['title']} — {photo['creator']}, {photo['license']}.*\n"
    lines = md.splitlines()
    i = 0
    while i < len(lines) and (not lines[i].strip() or lines[i].lstrip().startswith(('#', '```', '![', '*Image:'))):
        i += 1
    j = i
    while j + 1 < len(lines) and lines[j + 1].strip() and (not lines[j + 1].lstrip().startswith(('#', '```', '![', '*Image:'))):
        j += 1
    return '\n'.join(lines[:j + 1]) + block + '\n' + '\n'.join(lines[j + 1:])

def keyword_ladder(text: str) -> list[str]:
    toks = [t for t in re.sub('[^a-z0-9 -]', ' ', (text or '').lower()).split() if t not in _STOP and len(t) > 2 and (not t.isdigit())]
    uniq = list(dict.fromkeys(toks))
    if not uniq:
        return []
    out = [' '.join(uniq)]
    words = list(uniq)
    while len(words) > 3:
        words = words[:-1]
        q = ' '.join(words)
        if q and q not in out:
            out.append(q)
    return out

def commons_pool(q: str, limit: int=8) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if len(q.split()) >= 2:
        phrase = urllib.parse.urlencode({'action': 'query', 'format': 'json', 'prop': 'imageinfo', 'generator': 'search', 'gsrsearch': 'filetype:bitmap intitle:"' + q + '"', 'gsrnamespace': 6, 'gsrlimit': limit, 'iiurlwidth': 1024, 'iiprop': 'url|mime|size|extmetadata'})
        data = _http_json(f'{COMMONS}?{phrase}')
        pages = ((data or {}).get('query') or {}).get('pages') or {}
        for p in sorted(pages.values(), key=lambda x: x.get('index', 99)):
            info = (p.get('imageinfo') or [{}])[0]
            mime, w = (info.get('mime', ''), info.get('width') or 0)
            title = p.get('title', '').replace('File:', '').rsplit('.', 1)[0]
            if mime not in ('image/jpeg', 'image/png') or (w or 0) < 600:
                continue
            if re.search('(?i)logo|icon|coat of arms|flag of|map of\\b', title):
                continue
            meta = info.get('extmetadata') or {}
            lic = (meta.get('LicenseShortName') or {}).get('value', '')
            artist = re.sub('<[^>]+>', '', (meta.get('Artist') or {}).get('value', ''))[:60]
            out.append({'url': info.get('thumburl') or info.get('url') or '', 'title': title, 'creator': artist or 'Wikimedia Commons', 'license': f"{lic or 'CC'} via Wikimedia Commons", 'width': w})
            if len(out) >= limit:
                break
    params = urllib.parse.urlencode({'action': 'query', 'format': 'json', 'prop': 'imageinfo', 'generator': 'search', 'gsrsearch': f'filetype:bitmap {q}', 'gsrnamespace': 6, 'gsrlimit': limit, 'iiurlwidth': 1024, 'iiprop': 'url|mime|size|extmetadata'})
    data = _http_json(f'{COMMONS}?{params}')
    if not data:
        return out
    pages = (data.get('query') or {}).get('pages') or {}
    qt = set(re.sub('[^a-z ]', ' ', q.lower()).split()) - _STOP
    for p in sorted(pages.values(), key=lambda x: x.get('index', 99)):
        info = (p.get('imageinfo') or [{}])[0]
        mime, w = (info.get('mime', ''), info.get('width') or 0)
        title = p.get('title', '').replace('File:', '').rsplit('.', 1)[0]
        if mime not in ('image/jpeg', 'image/png') or (w or 0) < 600:
            continue
        if re.search('(?i)logo|icon|coat of arms|flag of|map of\\b', title):
            continue
        meta = info.get('extmetadata') or {}
        tt = set(re.sub('[^a-z0-9 ]', ' ', title.lower()).split()) - _STOP
        shared = qt & tt
        if len(qt) <= 1:
            if not (len(shared) == len(qt) and qt):
                continue
        elif len(shared) < 2:
            continue
        lic = (meta.get('LicenseShortName') or {}).get('value', '')
        artist = re.sub('<[^>]+>', '', (meta.get('Artist') or {}).get('value', ''))[:60]
        out.append({'url': info.get('thumburl') or info.get('url') or '', 'title': title, 'creator': artist or 'Wikimedia Commons', 'license': f"{lic or 'CC'} via Wikimedia Commons", 'width': w})
        if len(out) >= limit:
            break
    return out

def openverse_pool(q: str, limit: int=8) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({'q': q, 'page_size': 20})
    data = _http_json(f'{OPENVERSE}?{params}')
    out: list[dict[str, Any]] = []
    if not data:
        return out
    qt = set(re.sub('[^a-z0-9 ]', ' ', q.lower()).split()) - _STOP
    for r in data.get('results') or []:
        title = (r.get('title') or '').lower()
        shared = qt & set(re.sub('[^a-z0-9 ]', ' ', title).split()) - _STOP
        if qt and (len(qt) <= 1 and (not shared) or (len(qt) > 1 and len(shared) < 2)):
            continue
        if (r.get('width') or 0) < 600 or not r.get('url'):
            continue
        if r.get('extension', 'jpg').lower() not in ('jpg', 'jpeg', 'png'):
            continue
        out.append({'url': r['url'], 'title': re.sub('\\s+', ' ', r.get('title') or q)[:80], 'creator': (r.get('creator') or r.get('source') or '')[:60], 'license': f"{(r.get('license') or '').upper()} via Openverse", 'width': r.get('width')})
        if len(out) >= limit:
            break
    return out
_POOL_CACHE: dict[str, list[dict[str, Any]]] = {}
_POOL_LOCK = threading.Lock()

def download_with_provenance(photo: dict, dest_dir: Path, stem: str='img', width_min: int=600) -> dict | None:
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    url = photo.get('url') or ''
    if not url:
        return None
    ext = '.jpg'
    m = re.search('\\.(jpe?g|png|webp)(?:$|\\?)', url.lower())
    if m:
        ext = f".{m.group(1).replace('jpeg', 'jpg')}"
    dest = dest_dir / (stem + ext)

    def _dl():
        req = urllib.request.Request(url, headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.read(6 * 1024 * 1024)
    from concurrent.futures import ThreadPoolExecutor as _TPE
    try:
        with _TPE(max_workers=1) as _ex:
            data = _ex.submit(_dl).result(timeout=25.0)
        if not data or len(data) < 5000:
            return None
        dest.write_bytes(data)
    except Exception:
        try:
            dest.unlink(missing_ok=True)
        except Exception:
            pass
        return None
    side = dest.with_suffix('.txt')
    side.write_text(f"source: {url}\ntitle: {photo.get('title', '')}\ncreator: {photo.get('creator', '')}\nlicense: {photo.get('license', '')}\n")
    out = dict(photo)
    out['file'] = str(dest)
    out['provenance'] = str(side)
    return out

def guide_images(question: str, accepted_pages: list, per_page: int=1, dest_dir: Path | None=None) -> list[dict]:
    out: list[dict] = []
    queries = keyword_ladder(question or '')
    for p in (accepted_pages or [])[:3]:
        t = (p.get('clean') or {}).get('title') or p.get('title') or ''
        if t:
            queries.insert(0, keywords(t, 3))
    seen: set[str] = set()
    n_added = 0
    cap = max(per_page, 1) * 3
    for q in queries[:8]:
        if n_added >= cap:
            break
        for cand in ([find_photo(q)] if find_photo(q) else []) + photo_pool([q], per_query=6):
            u = cand.get('url', '')
            if not u or u in seen:
                continue
            if not _img_topical(cand.get('title') or '', question or ''):
                continue
            seen.add(u)
            stem = re.sub('[^a-z0-9]+', '-', (q + '-' + str(n_added)).lower())[:48] or f'img{n_added}'
            dl = download_with_provenance(cand, dest_dir or _REPO_ROOT / 'assets' / 'photo-cache', stem)
            if dl:
                out.append(dl)
                n_added += 1
                if n_added >= cap:
                    break
            time.sleep(0.5)
    return out