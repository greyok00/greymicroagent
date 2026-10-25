from __future__ import annotations
import re
from pathlib import Path
from urllib.parse import urlparse
_MAX_PAGE_BYTES = 3 * 1024 * 1024
_LONG_TEXT_PARAS = 2
_NAV_WALL_LINKS = 30

def _text_of(html: str) -> str:
    txt = re.sub('<script.*?</script>|<style.*?</style>', ' ', html, flags=re.S | re.I)
    return re.sub('<[^>]+>', ' ', txt)

def check_site(out: Path) -> dict:
    out = Path(out)
    checks: list = {}

    def _add(name: str, ok: bool, note: str) -> None:
        checks[name] = {'pass': bool(ok), 'note': note}
    index = out / 'index.html'
    if not index.exists() or index.stat().st_size < 200:
        _add('index_present', False, 'index.html missing or empty')
        return {'ok': False, 'checks': checks}
    html = index.read_text(errors='ignore')
    n_bytes = index.stat().st_size
    _add('index_present', True, f'{n_bytes} bytes')
    _add('size_sane', n_bytes <= _MAX_PAGE_BYTES, f'{n_bytes} bytes (cap {_MAX_PAGE_BYTES})')
    title = re.search('<title>(.*?)</title>', html, re.S)
    h1s = re.findall('<h1[ >]', html)
    paras = [re.sub('<[^>]+>', ' ', seg) for seg in re.split('</p>', html)]
    good_paras = len([p for p in paras if len(' '.join(p.split())) > 120])
    total_chars = len(' '.join(''.join(paras).split()))
    _add('title', bool(title and title.group(1).strip()), title.group(1)[:60] if title else 'missing')
    _add('h1', len(h1s) >= 1, f'{len(h1s)} H1 element(s)')
    _add('readable_text', good_paras >= _LONG_TEXT_PARAS or total_chars > 2000, f'{good_paras} paragraphs >120 chars (need {_LONG_TEXT_PARAS}; {total_chars} total chars)')
    broken, anchors = ([], set(re.findall('id="([^"]+)"', html)))
    for href in re.findall('href="([^"]+)"', html):
        if href.startswith(('http', 'mailto:', '//')):
            continue
        frag = ''
        path = href
        if '#' in href:
            path, frag = href.split('#', 1)
        if path and (not (out / path).exists()):
            broken.append(href)
        elif frag and frag not in anchors:
            broken.append(href)
    _add('internal_links', len(broken) == 0, 'all internal links resolve' if not broken else f'{len(broken)} broken (first: {broken[:2]})')
    missing_imgs = []
    n_imgs = 0
    for img in re.findall('<img[^>]+src="([^"]+)"', html):
        if img.startswith(('http', 'data:', '//')):
            continue
        n_imgs += 1
        if not (out / img).exists():
            missing_imgs.append(img)
    src_imgs = 0
    if out.name.endswith('_site'):
        src = out.parent / (out.name[:-len('_site')] + '.md')
        if src.exists():
            src_imgs = len(re.findall('^!\\[', src.read_text(errors='ignore'), re.M))
    _add('images', len(missing_imgs) == 0 and (src_imgs == 0 or n_imgs > 0), f'{n_imgs} local imgs referenced on page, {len(missing_imgs)} missing, {src_imgs} markdown-image refs in source')
    nav_clusters = re.findall('<nav.*?</nav>|<aside.*?</aside>', html, re.S | re.I) or []
    worst = 0
    for cluster in nav_clusters:
        n = len(re.findall('<a[ >]', cluster))
        txt = len(_text_of(cluster).strip())
        if txt < 1200:
            worst = max(worst, n)
    _add('no_nav_wall', worst < _NAV_WALL_LINKS, f'largest light nav cluster: {worst} links (cap {_NAV_WALL_LINKS})')
    ok = all((c['pass'] for c in checks.values()))
    return {'ok': ok, 'checks': checks}