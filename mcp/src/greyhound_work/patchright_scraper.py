from __future__ import annotations
import atexit
import json
import os
import re
import subprocess as _sp
import threading as _th
import time
from typing import Any, Dict, List, Optional
try:
    from patchright.sync_api import sync_playwright
    _HAS_PATCHRIGHT = True
except Exception:
    sync_playwright = None
    _HAS_PATCHRIGHT = False
try:
    from . import research_injection as _rij
except Exception:
    import research_injection as _rij
try:
    from . import browser_ports as _browser_ports
    from browser_session import eval_with_timeout
except Exception:
    try:
        import browser_ports as _browser_ports
    except Exception:
        _browser_ports = None
_DISPLAY_RECLAIM_LOG = os.path.expanduser('~/.cache/greyhound/xvfb-reaper.log')
_HTML_CAP = 400000
_BOILER_LINES = [re.compile('(?i)^.{0,80}\\bcookie\\s+(policy|notice|consent|banner).{0,120}$'), re.compile('(?i)^.{0,60}\\ball\\s+rights\\s+reserved\\b.{0,80}$'), re.compile('(?i)^.{0,60}\\bsubscribe\\s+(now|to\\s+our\\s+newsletter)\\b.{0,120}$'), re.compile('(?i)^.{0,40}\\bfollow\\s+us\\s+on\\b.{0,120}$')]
_BOILER_INLINE = [re.compile('(?i)accept\\s+all\\s+cookies?\\b.{0,60}'), re.compile('(?i)skip\\s+to\\s+content\\b'), re.compile('(?i)please\\s+enable\\s+(javascript|cookies)\\b.{0,60}')]
_SCROLL_JS = "() => new Promise(res => {\n    let h = document.documentElement.scrollHeight, y = 0, n = 0;\n    const step = () => {\n        window.scrollTo(0, y); y += 900; n++;\n        h = document.documentElement.scrollHeight;\n        if (y < h && n < 30) { setTimeout(step, 120); }\n        else { window.scrollTo(0, 0); res(n); }\n    };\n    if (document.readyState !== 'complete') {\n        window.addEventListener('load', () => {\n            h = document.documentElement.scrollHeight; step();\n        }, { once: true });\n    } else { step(); }\n})"
_LINKS_JS = "() => Array.from(document.querySelectorAll('a[href]')).slice(0, 800).map(a => ({\n    href: a.href, text: (a.innerText || a.textContent || '').trim().slice(0, 200)\n})).filter(x => x.href.startsWith('http'))"
_IMAGES_JS = "() => Array.from(document.querySelectorAll('img[data-src], img[src]')).slice(0, 400).map(i => ({\n    src: i.currentSrc || i.src || i.dataset.src || '', alt: (i.alt || '').slice(0, 200),\n    w: i.naturalWidth || 0, h: i.naturalHeight || 0\n})).filter(i => i.src.startsWith('http'))"
_VIDEO_TAG_JS = "() => Array.from(document.querySelectorAll('video')).map(v => ({\n    src: (v.currentSrc || v.src || ''), title: (v.title || '').slice(0, 200)\n})).filter(v => v.src)"
_IFRAME_VIDEO_JS = "() => Array.from(document.querySelectorAll('iframe')).map(f => ({\n    src: f.src, title: (f.title || '').slice(0, 200)\n})).filter(f => f.src && /youtube\\.com|youtu\\.be|vimeo\\.com|player\\./.test(f.src))"
_TABLES_JS = "() => Array.from(document.querySelectorAll('table')).slice(0, 60).map(t => {\n    const rows = Array.from(t.querySelectorAll('tr')).slice(0, 250).map(tr =>\n        Array.from(tr.querySelectorAll('th,td')).slice(0, 30).map(c => (c.innerText || '').trim().slice(0, 400)));\n    const cap = t.querySelector('caption');\n    return {rows, caption: cap ? (cap.innerText || '').trim().slice(0, 300) : ''};\n}).filter(t => t.rows && t.rows.length)"
_HEADINGS_JS = "() => Array.from(document.querySelectorAll('h1,h2,h3,h4')).slice(0, 120).map(h => ({\n    level: h.tagName, text: (h.innerText || '').trim().slice(0, 400), id: h.id || ''\n})).filter(h => h.text)"
_CODE_JS = "() => Array.from(document.querySelectorAll('pre code, pre')).slice(0, 40)\n    .map(c => (c.innerText || '').slice(0, 8000)).filter(s => s.trim().length > 20)"
_META_JS = "() => {\n    const meta = {};\n    document.querySelectorAll('meta[name], meta[property]').forEach(t => {\n        const k = t.name || t.property || '';\n        if (k && t.content) meta[k] = t.content.slice(0, 400);\n    });\n    return meta;\n}"
_AUDIO_JS = "() => Array.from(document.querySelectorAll('audio')).map(a => ({\n    src: a.currentSrc || a.src || '',\n    title: a.title || ''\n})).filter(a => a.src)"
_PDF_JS = '() => {\n    const pdfs = [];\n    // PDF links\n    document.querySelectorAll(\'a[href]\').forEach(a => {\n        const href = a.href;\n        if (href.toLowerCase().endsWith(\'.pdf\')) {\n            pdfs.push({src: href, title: a.title || a.textContent || \'\'});\n        }\n    });\n    // PDF embed/object\n    document.querySelectorAll(\'embed[type="application/pdf"], object[type="application/pdf"]\').forEach(el => {\n        const src = el.src || el.data || \'\';\n        if (src) pdfs.push({src: src, title: el.title || \'\'});\n    });\n    return pdfs;\n}'
_CANVAS_JS = "() => Array.from(document.querySelectorAll('canvas')).map(c => ({\n    width: c.width,\n    height: c.height\n}))"
_IFRAME_JS = "() => Array.from(document.querySelectorAll('iframe')).map(f => ({\n    src: f.src,\n    title: f.title || ''\n})).filter(f => f.src)"

def chrome_exe() -> str:
    if _HAS_PATCHRIGHT:
        try:
            with sync_playwright() as p:
                cand = p.chromium.executable_path
            if cand and os.path.exists(cand):
                return cand
        except Exception:
            pass
    for cand in ('/usr/bin/chromium', '/usr/bin/chromium-browser', '/usr/bin/google-chrome-stable'):
        if os.path.exists(cand):
            return cand
    import glob as _glob
    for d in sorted(_glob.glob(os.path.expanduser('~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome')), reverse=True):
        if os.path.exists(d):
            return d
    raise FileNotFoundError('no chromium executable found for scraper')

def _shutdown() -> None:
    if PatchrightScraper._shutdown_done:
        return
    PatchrightScraper._shutdown_done = True
    try:
        if PatchrightScraper._ctx is not None:
            PatchrightScraper._ctx.close()
    except Exception:
        pass
    try:
        if PatchrightScraper._pw is not None:
            PatchrightScraper._pw.stop()
    except Exception:
        pass
    PatchrightScraper._ctx = None
    PatchrightScraper._browser = None
    PatchrightScraper._pw = None
    try:
        if PatchrightScraper._xvfb is not None:
            PatchrightScraper._xvfb.terminate()
            time.sleep(0.4)
            PatchrightScraper._xvfb.kill()
    except Exception:
        pass
    if PatchrightScraper._display_lockfile:
        try:
            os.unlink(PatchrightScraper._display_lockfile)
        except Exception:
            pass

class PatchrightScraper:
    _CLS_LOCK = _th.RLock()
    _pw: Any = None
    _browser: Any = None
    _ctx: Any = None
    _xvfb: Any = None
    _display: str = ''
    _display_lockfile: str = ''
    _profile_dir: str = ''
    _pages_fetched: int = 0
    _shutdown_done: bool = False
    _display_reclaims: List[Dict[str, Any]] = []

    def __init__(self, stealth_level: str='high', timeout: int=25, user_agent_pool: Optional[List[str]]=None):
        self.stealth_level = stealth_level
        self.timeout = timeout
        self.user_agent_pool = user_agent_pool or ['patchright-managed']
        self._page: Any = None
        self._consecutive_failures = 0

    def _ensure_xvfb(self) -> str:
        if PatchrightScraper._xvfb is not None and PatchrightScraper._display:
            return PatchrightScraper._display
        env_display = os.environ.get('DISPLAY', '').strip()
        if env_display and env_display != ':0':
            n = env_display.lstrip(':')
            try:
                n_int = int(n)
            except ValueError:
                n_int = None
            if (n_int is None or 60 <= n_int <= 199) and os.path.exists(f'/tmp/.X11-unix/X{n}'):
                PatchrightScraper._display = env_display
                PatchrightScraper._display_lockfile = ''
                PatchrightScraper._xvfb = None
                return PatchrightScraper._display

        def _display_serves(n: int) -> bool:
            try:
                r = _sp.run(['pgrep', '-f', f'Xvfb :{n} '], stdout=_sp.PIPE)
            except Exception:
                return True
            for tok in r.stdout.decode().split():
                try:
                    if open(f'/proc/{tok}/comm').read().strip() == 'Xvfb':
                        return True
                except Exception:
                    continue
            return False
        for n in range(90, 100):
            xsocket = f'/tmp/.X11-unix/X{n}'
            lockfile = f'/tmp/greyhound-xvfb-{n}.lock'
            if _browser_ports is not None:
                try:
                    reclaim = _browser_ports.reap_orphan_display(n)
                except Exception as exc:
                    reclaim = {'display': n, 'reclaimed': False, 'reason': f'reaper error: {exc}'}
                if reclaim.get('reclaimed'):
                    PatchrightScraper._display_reclaims.append(reclaim)
                    try:
                        os.makedirs(os.path.dirname(_DISPLAY_RECLAIM_LOG), exist_ok=True)
                        with open(_DISPLAY_RECLAIM_LOG, 'a') as f:
                            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} reclaimed orphan Xvfb :{n} pids={reclaim.get('killed')}\n")
                    except Exception:
                        pass
            if os.path.exists(xsocket) and (not os.path.exists(lockfile)):
                if _display_serves(n):
                    continue
                for stale in (xsocket, f'/tmp/.X{n}-lock'):
                    try:
                        os.unlink(stale)
                    except Exception:
                        pass
            try:
                if os.path.exists(lockfile):
                    try:
                        owner = int(open(lockfile, 'r').read().strip() or '0')
                        os.kill(owner, 0)
                    except Exception:
                        owner_dead = True
                    else:
                        owner_dead = False
                    if owner_dead:
                        for stale in (lockfile, xsocket, f'/tmp/.X{n}-lock'):
                            try:
                                os.unlink(stale)
                            except Exception:
                                pass
                if os.path.exists(lockfile) and (not os.path.exists(xsocket)):
                    os.unlink(lockfile)
                fd = os.open(lockfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
            except FileExistsError:
                continue
            except Exception:
                continue
            try:
                proc = _sp.Popen(['Xvfb', f':{n}', '-screen', '0', '1400x1000x24', '-nolisten', 'tcp'], stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
            except Exception:
                try:
                    os.unlink(lockfile)
                except Exception:
                    pass
                continue
            time.sleep(0.8)
            if os.path.exists(xsocket):
                PatchrightScraper._xvfb = proc
                PatchrightScraper._display = f':{n}'
                PatchrightScraper._display_lockfile = lockfile
                return PatchrightScraper._display
            try:
                os.unlink(lockfile)
            except Exception:
                pass
            continue
        allow_main = os.environ.get('GREYHOUND_ALLOW_MAIN_DISPLAY', '').lower() in ('1', 'true', 'yes')
        if allow_main:
            n = 0
            xsocket = f'/tmp/.X11-unix/X{n}'
            lockfile = f'/tmp/greyhound-xvfb-{n}.lock'
            if os.path.exists(xsocket) and (not os.path.exists(lockfile)):
                try:
                    if os.path.exists(lockfile) and (not os.path.exists(xsocket)):
                        os.unlink(lockfile)
                    fd = os.open(lockfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    os.write(fd, str(os.getpid()).encode())
                    os.close(fd)
                except FileExistsError:
                    pass
                except Exception:
                    pass
                else:
                    try:
                        proc = _sp.Popen(['Xvfb', f':{n}', '-screen', '0', '1400x1000x24', '-nolisten', 'tcp'], stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
                    except Exception:
                        try:
                            os.unlink(lockfile)
                        except Exception:
                            pass
                    else:
                        time.sleep(0.8)
                        if os.path.exists(xsocket):
                            PatchrightScraper._xvfb = proc
                            PatchrightScraper._display = f':{n}'
                            PatchrightScraper._display_lockfile = lockfile
                            return PatchrightScraper._display
                    try:
                        os.unlink(lockfile)
                    except Exception:
                        pass
        raise RuntimeError('no display could be claimed (checked :90-:99 and :0 if allowed)')

    def _get_browser(self) -> Any:
        with PatchrightScraper._CLS_LOCK:
            if not _HAS_PATCHRIGHT:
                raise RuntimeError('patchright not installed (pip install patchright)')
            if PatchrightScraper._browser is not None:
                try:
                    if PatchrightScraper._browser.is_connected():
                        return PatchrightScraper._browser
                except Exception:
                    pass
                PatchrightScraper._browser = None
            if PatchrightScraper._pw is None:
                PatchrightScraper._pw = sync_playwright().start()
            disp = self._ensure_xvfb()
            if not PatchrightScraper._profile_dir:
                PatchrightScraper._profile_dir = f'/tmp/greyhound-profile-{os.getpid()}'
            env = dict(os.environ)
            env['DISPLAY'] = disp
            _exec = chrome_exe()
            ctx = PatchrightScraper._pw.chromium.launch_persistent_context(user_data_dir=PatchrightScraper._profile_dir, executable_path=_exec, headless=False, args=['--no-first-run', '--disable-gpu', '--lang=en-US', '--window-size=1400,1000', '--disable-dev-shm-usage'], env=env)
            PatchrightScraper._ctx = ctx
            PatchrightScraper._browser = ctx.browser
            return ctx

    def _get_page(self) -> Any:
        with PatchrightScraper._CLS_LOCK:
            if self._page is not None:
                try:
                    if not self._page.is_closed():
                        return self._page
                except Exception:
                    pass
                self._page = None
            ctx = self._get_browser()
            page = ctx.new_page()
            try:
                page.set_default_timeout(20000)
                page.on('dialog', lambda d: d.dismiss())
                page.on('download', lambda d: d.cancel())
            except Exception:
                pass
            self._page = page
            return page

    def _reset_page(self) -> None:
        try:
            if self._page is not None and (not self._page.is_closed()):
                self._page.close()
        except Exception:
            pass
        self._page = None

    def fetch_url(self, url: str, selector: str='body', custom_headers: Optional[Dict[str, str]]=None) -> Dict[str, Any]:
        del custom_headers
        if os.environ.get('GREYHOUND_ALLOW_PRIVATE_BROWSER', '').strip().lower() in ('1', 'true', 'yes'):
            return self._fetch_url_private(url, selector)
        start_time = time.time()
        last_error = ''
        for attempt in (1, 2):
            if attempt == 2 and any((w in last_error for w in ('closed', 'wedge', 'timeout wall'))):
                break
            try:
                try:
                    from . import browser_session as _bs
                except ImportError:
                    import browser_session as _bs
                r = _bs.fetch_text(url)
                if r.get('ok'):
                    r.setdefault('attempt', attempt)
                    r['display_reclaims'] = list(PatchrightScraper._display_reclaims)
                    PatchrightScraper._pages_fetched += 1
                    self._consecutive_failures = 0
                    return r
                last_error = str(r.get('error') or 'empty result')[:300]
            except Exception as e:
                last_error = f'{type(e).__name__}: {e}'[:300]
            try:
                try:
                    from . import browser_session as _bs
                except ImportError:
                    import browser_session as _bs
                _bs.drop_connection()
            except Exception:
                pass
        return {'ok': False, 'url': url, 'error': last_error or 'fetch failed', 'elapsed_s': round(time.time() - start_time, 2)}

    def _fetch_url_private(self, url: str, selector: str='body') -> Dict[str, Any]:
        start_time = time.time()
        last_error = ''
        for attempt in (1, 2):
            try:
                page = self._get_page()
                resp = page.goto(url, wait_until='domcontentloaded', timeout=self.timeout * 1000)
                try:
                    page.wait_for_load_state('load', timeout=8000)
                except Exception:
                    pass
                time.sleep(0.6)
                body_text = page.locator(selector).first.inner_text(timeout=10000)
                if not (body_text or '').strip():
                    raise RuntimeError('empty body text (bot-wall, blank page, or JS-only)')
                title = page.title() or ''
                status = resp.status if resp is not None else 200
                final_url = page.url or url
                html_content = page.content() or ''
                html_capped = False
                if len(html_content) > _HTML_CAP:
                    html_content = html_content[:_HTML_CAP]
                    html_capped = True
                scroll_steps = 0
                try:
                    scroll_steps = eval_with_timeout(page, _SCROLL_JS)
                except Exception:
                    scroll_steps = 0
                media = self.extract_media(page)
                try:
                    metadata = eval_with_timeout(page, _META_JS) or {}
                except Exception:
                    metadata = {}
                metadata['extraction_method'] = 'patchright_private_stealth'
                metadata['scroll_steps'] = scroll_steps
                cleaned, inj_flags = _rij.sanitize_text(body_text)
                self._consecutive_failures = 0
                PatchrightScraper._pages_fetched += 1
                return {'ok': True, 'url': url, 'final_url': final_url, 'title': title, 'status_code': status, 'text': cleaned, 'raw_text': body_text, 'html': html_content, 'html_capped': html_capped, 'metadata': metadata, 'links': media.get('links', []), 'images': media.get('images', []), 'videos': media.get('videos', []), 'tables': media.get('tables', []), 'headings': media.get('headings', []), 'code_blocks': media.get('code_blocks', []), 'audios': media.get('audios', []), 'pdfs': media.get('pdfs', []), 'canvases': media.get('canvases', []), 'iframes': media.get('iframes', []), 'injection_flags': inj_flags, 'injection_scanned': True, 'display_reclaims': list(PatchrightScraper._display_reclaims), 'attempt': attempt, 'elapsed_s': round(time.time() - start_time, 2)}
            except Exception as e:
                last_error = f'{type(e).__name__}: {e}'[:300]
                self._consecutive_failures += 1
                self._reset_page()
                if self._consecutive_failures >= 2 and attempt == 1:
                    with PatchrightScraper._CLS_LOCK:
                        try:
                            if PatchrightScraper._browser is not None:
                                PatchrightScraper._browser.close()
                        except Exception:
                            pass
                        PatchrightScraper._browser = None
        return {'ok': False, 'url': url, 'error': last_error or 'fetch failed', 'elapsed_s': round(time.time() - start_time, 2)}

    def extract_media(self, page: Any) -> Dict[str, Any]:
        links: List[Dict[str, str]] = []
        images: List[Dict[str, str]] = []
        videos: List[Dict[str, str]] = []
        tables: List[Any] = []
        headings: List[Dict[str, str]] = []
        code_blocks: List[str] = []
        audios: List[Dict[str, str]] = []
        pdfs: List[Dict[str, str]] = []
        canvases: List[Dict[str, int]] = []
        iframes: List[Dict[str, str]] = []
        jobs = [('links', _LINKS_JS), ('images', _IMAGES_JS), ('videos', _VIDEO_TAG_JS), ('videos', _IFRAME_VIDEO_JS), ('tables', _TABLES_JS), ('headings', _HEADINGS_JS), ('code', _CODE_JS), ('audios', _AUDIO_JS), ('pdfs', _PDF_JS), ('canvases', _CANVAS_JS), ('iframes', _IFRAME_JS)]
        for label, js in jobs:
            try:
                raw = eval_with_timeout(page, js)
            except Exception:
                continue
            if not isinstance(raw, list):
                continue
            if label == 'links':
                for r in raw:
                    if isinstance(r, dict) and r.get('href', '').startswith('http'):
                        links.append({'href': r['href'], 'text': r.get('text', '')})
            elif label == 'images':
                for r in raw:
                    if isinstance(r, dict) and r.get('src', '').startswith('http'):
                        w = r.get('w', 0) or 0
                        h = r.get('h', 0) or 0
                        if w and h and (w < 32) and (h < 32):
                            continue
                        images.append({'src': r['src'], 'alt': r.get('alt', ''), 'w': w, 'h': h})
            elif label == 'videos':
                for r in raw:
                    if isinstance(r, dict) and r.get('src') and (r not in videos):
                        videos.append({'src': r['src'], 'title': r.get('title', '')})
            elif label == 'tables':
                for t in raw:
                    if isinstance(t, dict) and t.get('rows'):
                        tables.append(t)
            elif label == 'headings':
                for r in raw:
                    if isinstance(r, dict) and r.get('text'):
                        headings.append({'level': r.get('level', ''), 'text': r.get('text', '')})
            elif label == 'code':
                for s in raw:
                    if isinstance(s, str) and s.strip():
                        code_blocks.append(s)
            elif label == 'audios':
                for r in raw:
                    if isinstance(r, dict) and r.get('src'):
                        audios.append({'src': r['src'], 'title': r.get('title', '')})
            elif label == 'pdfs':
                for r in raw:
                    if isinstance(r, dict) and r.get('src'):
                        pdfs.append({'src': r['src'], 'title': r.get('title', '')})
            elif label == 'canvases':
                for r in raw:
                    if isinstance(r, dict):
                        canvases.append({'width': r.get('width', 0), 'height': r.get('height', 0)})
            elif label == 'iframes':
                for r in raw:
                    if isinstance(r, dict) and r.get('src'):
                        iframes.append({'src': r['src'], 'title': r.get('title', '')})
        return {'links': links, 'images': images, 'videos': videos, 'tables': tables, 'headings': headings, 'code_blocks': code_blocks, 'audios': audios, 'pdfs': pdfs, 'canvases': canvases, 'iframes': iframes}

    def extract_links(self, url: str, selector: str='a', attribute: str='href') -> List[Dict[str, str]]:
        del selector, attribute
        result = self.fetch_url(url)
        if not result.get('ok'):
            return [{'url': url, 'error': result.get('error', 'fetch failed')}]
        return result.get('links', [])

    def _clean_text(self, text: str) -> str:
        if not text:
            return ''
        text = re.sub('[ \\t]+', ' ', text)
        text = re.sub(' ?\\n ?', '\n', text)
        for pat in _BOILER_LINES:
            text = re.sub(pat, '', text)
        for pat in _BOILER_INLINE:
            text = re.sub(pat, '', text)
        text = re.sub('\\n{3,}', '\n\n', text)
        return text.strip()

    def _extract_metadata(self, fetch_result: Dict[str, Any]) -> Dict[str, Any]:
        metadata = {}
        if 'title' in fetch_result:
            metadata['title'] = fetch_result['title']
        metadata['extraction_method'] = 'patchright_private_stealth'
        return metadata

    def health_check(self) -> Dict[str, Any]:
        running = False
        display = ''
        with PatchrightScraper._CLS_LOCK:
            display = PatchrightScraper._display
            if PatchrightScraper._ctx is not None:
                try:
                    brow = PatchrightScraper._ctx.browser
                    running = bool(brow.is_connected()) if brow else False
                except Exception:
                    running = False
        slot_alive = False
        lane = 'cdp-slot-browser (patchright headless via connect_over_cdp)'
        if os.environ.get('GREYHOUND_ALLOW_PRIVATE_BROWSER', '').strip().lower() in ('1', 'true', 'yes'):
            lane = 'private stealth browser (opt-in)'
            slot_alive = running
        else:
            try:
                try:
                    from . import browser_session as _bs
                except ImportError:
                    import browser_session as _bs
                slot_alive = _bs.cdp_alive()
            except Exception:
                slot_alive = False
        return {'scraper_stealth_level': self.stealth_level, 'scraper_timeout': self.timeout, 'lane': lane, 'slot_browser_alive': slot_alive, 'private_browser_running': running, 'private_display': display or 'not-started', 'pages_fetched_this_process': PatchrightScraper._pages_fetched, 'display_reclaims': list(PatchrightScraper._display_reclaims), 'patchright_installed': _HAS_PATCHRIGHT}

    def health(self) -> Dict[str, Any]:
        return self.health_check()

def scrape_url(url: str, selector: str='body', timeout: int=25) -> Dict[str, Any]:
    scraper = PatchrightScraper(timeout=timeout)
    return scraper.fetch_url(url, selector=selector)

def quick_scrape(url: str) -> Optional[str]:
    result = scrape_url(url)
    if result.get('ok'):
        return result.get('text')
    return None
if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        result = scrape_url(sys.argv[1])
        slim = {k: v for k, v in result.items() if k not in ('raw_text', 'html')}
        if 'text' in slim and isinstance(slim['text'], str):
            slim['text'] = slim['text'][:2000]
        print(json.dumps(slim, indent=2)[:4000])
    else:
        print('Usage: python patchright_scraper.py <url>')