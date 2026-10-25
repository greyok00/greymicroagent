from __future__ import annotations
import os
import re
import threading
import time
import urllib.request
from contextlib import contextmanager
from typing import Any, Dict, Optional
try:
    from . import browser_ports
except ImportError:
    import browser_ports
try:
    from .patchright_scraper import _HTML_CAP, _SCROLL_JS, _LINKS_JS, _IMAGES_JS, _VIDEO_TAG_JS, _IFRAME_VIDEO_JS, _TABLES_JS, _HEADINGS_JS, _CODE_JS, _META_JS, _AUDIO_JS, _PDF_JS, _CANVAS_JS, _IFRAME_JS, _BOILER_LINES, _BOILER_INLINE
    from . import research_injection as _rij
except ImportError:
    from patchright_scraper import _HTML_CAP, _SCROLL_JS, _LINKS_JS, _IMAGES_JS, _VIDEO_TAG_JS, _IFRAME_VIDEO_JS, _TABLES_JS, _HEADINGS_JS, _CODE_JS, _META_JS, _AUDIO_JS, _PDF_JS, _CANVAS_JS, _IFRAME_JS, _BOILER_LINES, _BOILER_INLINE
    import research_injection as _rij
DEFAULT_TASK = 'task-3'
try:
    from patchright.sync_api import sync_playwright
except Exception as e:
    raise ImportError(f'patchright is required for the session browser ({e}); no vanilla playwright fallback exists by design')

def _cfg() -> dict:
    return browser_ports.resolve(os.environ.get('RESEARCH_TASK', DEFAULT_TASK))

def _slot_key() -> str:
    try:
        return str(_cfg().get('key') or '')
    except Exception:
        return ''

def cdp_url() -> str:
    return browser_ports.cdp_http(_cfg())

def cdp_alive(timeout: float=2.0) -> bool:
    try:
        with urllib.request.urlopen(cdp_url() + '/json/version', timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False

def ensure_daemon(wait_s: float=45.0) -> bool:
    return bool(browser_ports.ensure(_cfg(), wait_s=int(wait_s)))
_CONN_LOCK = threading.Lock()
_CONNECTIONS: Dict[int, Dict[str, Any]] = {}

def _diag_dump(err: str, path: str='/tmp/greyhound-sync-start-diag.log') -> None:
    try:
        import sys as _sys
        import traceback as _tb
        ident = threading.get_ident()
        this = _sys._current_frames().get(ident)
        lines = ['', time.strftime('%Y-%m-%dT%H:%M:%S'), f'ident={ident} slot={_slot_key()} err={err[:200]}']
        if this:
            lines += _tb.format_stack(this)
        for tid, fr in _sys._current_frames().items():
            lines.append(f'--- thread {tid}')
            frame_lines = _tb.format_stack(fr)
            lines += frame_lines[-6:]
        with open(path, 'a', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
    except Exception:
        pass

def _discard_stale(conn: Dict[str, Any]) -> None:
    if not conn:
        return
    pw = conn.get('pw')
    if pw is not None:
        try:
            pw.stop()
        except Exception:
            pass

def _reset_loop_sentinel() -> None:
    try:
        import asyncio
        asyncio._set_running_loop(None)
    except Exception:
        pass

def _connection() -> Dict[str, Any]:
    ident = threading.get_ident()
    key = (ident, _slot_key())
    with _CONN_LOCK:
        conn = _CONNECTIONS.get(ident)
    if conn:
        if conn['key'] != key:
            _discard_stale(conn)
            with _CONN_LOCK:
                _CONNECTIONS.pop(ident, None)
            conn = None
        else:
            try:
                if conn['browser'].is_connected():
                    return conn
            except Exception:
                pass
            _discard_stale(conn)
            with _CONN_LOCK:
                _CONNECTIONS.pop(ident, None)
            conn = None
    if not cdp_alive():
        if not ensure_daemon():
            raise RuntimeError(f'the {_slot_key() or DEFAULT_TASK} greyhound browser is not reachable and could not be launched')
    try:
        pw = sync_playwright().start()
    except Exception as pw_exc:
        if 'asyncio loop' not in str(pw_exc):
            raise
        _diag_dump(str(pw_exc))
        _discard_stale(conn)
        with _CONN_LOCK:
            leaked = _CONNECTIONS.pop(ident, None)
        _discard_stale(leaked)
        _reset_loop_sentinel()
        pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(cdp_url())
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    conn = {'key': key, 'pw': pw, 'browser': browser, 'ctx': ctx, 'page': page}
    with _CONN_LOCK:
        _CONNECTIONS[ident] = conn
    return conn

def page() -> Any:
    return _connection()['page']

def browser() -> Any:
    return _connection()['browser']

def context() -> Any:
    return _connection()['ctx']

def drop_connection() -> None:
    ident = threading.get_ident()
    with _CONN_LOCK:
        conn = _CONNECTIONS.pop(ident, None)
    if conn:
        try:
            conn['pw'].stop()
        except Exception:
            pass

@contextmanager
def session_page():
    try:
        yield page()
    finally:
        drop_connection()

def _clean_text(text: str) -> str:
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

def _safe_eval(js: str, fallback):
    try:
        return page().evaluate(js)
    except Exception:
        return fallback

def fetch_text(url: str, max_chars: Optional[int]=None, settle_ms: int=1200) -> dict:
    started = time.time()
    conn = _connection()
    pg = conn['ctx'].new_page()
    try:
        pg.set_default_timeout(60000)
    except Exception:
        pass
    own_tab = True
    status = 0
    error = ''
    try:
        resp = pg.goto(url, timeout=60000, wait_until='domcontentloaded')
        status = int(getattr(resp, 'status', 0) or 0)
    except Exception as e:
        try:
            pg.close()
        except Exception:
            pass
        return {'ok': False, 'url': url, 'error': f'navigation failed: {type(e).__name__}: {str(e)[:200]}', 'domain': '', 'tier': '', 'lane': 'cdp-slot'}
    if settle_ms:
        try:
            pg.wait_for_timeout(settle_ms)
        except Exception:
            pass
    try:
        scroll_steps = int(eval_with_timeout(pg, _SCROLL_JS) or 0)
    except Exception:
        scroll_steps = 0
    raw_text = ''
    try:
        raw_text = pg.locator('body').inner_text()
    except Exception as e:
        error = f'body extract failed: {type(e).__name__}'
    html = ''
    try:
        html = pg.content()
    except Exception:
        pass
    html_capped = False
    if len(html) > _HTML_CAP:
        html = html[:_HTML_CAP]
        html_capped = True
    links = _safe_eval(_LINKS_JS, []) or []
    images = _safe_eval(_IMAGES_JS, []) or []
    videos = _safe_eval(_VIDEO_TAG_JS, []) or []
    videos += _safe_eval(_IFRAME_VIDEO_JS, []) or []
    tables = _safe_eval(_TABLES_JS, []) or []
    headings = _safe_eval(_HEADINGS_JS, []) or []
    code_blocks = _safe_eval(_CODE_JS, []) or []
    audios = _safe_eval(_AUDIO_JS, []) or []
    pdfs = _safe_eval(_PDF_JS, []) or []
    canvases = _safe_eval(_CANVAS_JS, []) or []
    iframes = _safe_eval(_IFRAME_JS, []) or []
    try:
        meta = eval_with_timeout(pg, _META_JS) or {}
    except Exception:
        meta = {}
    text, inj_flags = _rij.sanitize_text(raw_text)
    text = _clean_text(text)
    if max_chars and max_chars > 0 and (len(text) > max_chars):
        text = text[:max_chars].rstrip()
        error = error or f'text capped by caller at {max_chars}'
    title = ''
    try:
        title = pg.title()
    except Exception:
        pass
    final_url = url
    try:
        final_url = pg.url
    except Exception:
        pass
    parsed_dom = ''
    try:
        from urllib.parse import urlparse as _up
        parsed_dom = _up(final_url).netloc.lower()
        if parsed_dom.startswith('www.'):
            parsed_dom = parsed_dom[4:]
    except Exception:
        pass
    h2s = [(h.get('text') or '').strip() for h in headings if h.get('level') == 'h2' and h.get('text')][:20]
    ok = bool(text.strip())
    if own_tab:
        try:
            pg.close()
        except Exception:
            pass
    return {'ok': ok, 'url': url, 'final_url': final_url, 'title': title, 'status_code': status, 'error': error if not ok else '', 'chars': len(text), 'text': text, 'raw_text': raw_text, 'html': html, 'html_capped': html_capped, 'links': links, 'images': images, 'videos': videos, 'tables': tables, 'headings': headings, 'code_blocks': code_blocks, 'audios': audios, 'pdfs': pdfs, 'canvases': canvases, 'iframes': iframes, 'injection_flags': inj_flags, 'injection_scanned': True, 'h2s': h2s, 'clean': {'canonical_url': final_url, 'h2s': h2s, 'body_text': text, 'excerpt': text[:600]}, 'metadata': {**(meta if isinstance(meta, dict) else {}), 'extraction_method': 'cdp_slot_browser', 'scroll_steps': scroll_steps}, 'domain': parsed_dom, 'lane': 'cdp-slot', 'elapsed_s': round(time.time() - started, 2)}
_EVAL_TIMEOUT_S = 5.0

def eval_with_timeout(page, js: str, timeout_s: float=_EVAL_TIMEOUT_S):
    done = threading.Event()
    import threading as _t

    def _observer():
        end = time.time() + timeout_s
        while time.time() < end and (not done.is_set()):
            time.sleep(0.5)
        if done.is_set():
            return
        _kill_page_target_cdp()
    obs = _t.Thread(target=_observer, daemon=True)
    obs.start()
    try:
        res = page.evaluate(js)
        return res
    finally:
        done.set()

def _kill_page_target_cdp() -> None:
    import json as _json
    import urllib.request as _ur
    try:
        import browser_ports as _bp
        cfg = _bp.task_cfg()
    except Exception:
        return
    try:
        targets = _json.loads(_ur.urlopen(f"http://127.0.0.1:{cfg['port']}/json/list", timeout=5).read())
        pages = [t for t in targets if t.get('type') == 'page']
        for t in pages[:2]:
            try:
                _ur.urlopen(_ur.Request(f"http://127.0.0.1:{cfg['port']}/json/close/{t['id']}", method='PUT'), timeout=5)
            except Exception:
                pass
    except Exception:
        pass