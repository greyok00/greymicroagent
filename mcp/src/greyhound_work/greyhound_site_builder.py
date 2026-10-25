from __future__ import annotations
import argparse
import os
import re
import sys
from pathlib import Path
import site_render

def render() -> int:
    ap = argparse.ArgumentParser(description='Master Guide -> full static website')
    ap.add_argument('guide', help='Master Guide .md file')
    ap.add_argument('-o', '--out', default='', help='Site output dir (default: <guide-stem>_site beside the guide)')
    ap.add_argument('--title', default='', help='Site title override')
    ap.add_argument('--max-images', type=int, default=200, help='Images to download (default 200; 0 disables)')
    ap.add_argument('--keep-remote', action='store_true', help='Never download; embed all images by their remote URL')
    ap.add_argument('--theme', default='master', help='grey kit theme applied as the page default')
    ap.add_argument('--no-scrub', action='store_true', help='Skip the nav-chrome scrub (guide_scrub.py)')
    a = ap.parse_args()
    import markdown
    guide = Path(a.guide)
    md_text = guide.read_text(errors='replace')
    scrub_stats = None
    if not a.no_scrub:
        try:
            from guide_scrub import scrub_guide_md
            md_text, scrub_stats = scrub_guide_md(md_text)
        except Exception:
            scrub_stats = None
    m = re.search('^#\\s+(.*)$', md_text, re.M)
    title = a.title or (m.group(1).strip() if m else guide.stem.replace('-', ' '))
    out = Path(a.out) if a.out else guide.with_name(guide.stem + '_site')
    out.mkdir(parents=True, exist_ok=True)
    assets = out / 'assets' / 'img'
    assets.mkdir(parents=True, exist_ok=True)
    site_render.ensure_kit(out)
    try:
        import photos
        if '*Image:' not in md_text:
            q = photos.keywords(title, 4) or photos.keywords(title, 2) or title
            ph = photos.find_photo(q)
            if not (ph and ph.get('url')):
                hits = [h for h in photos.searx_image_hits(q, 6) if h.get('url')]
                ph = hits[0] if hits else None
            if ph and ph.get('url'):
                md_text = photos.insert_photo(md_text, ph, title)
    except Exception:
        pass
    md_text, img_report = site_render.download_images(md_text, assets, a.max_images, a.keep_remote, src_dir=guide.parent)
    when = os.popen("date -u '+%Y-%m-%d %H:%M UTC'").read().strip()
    title = title.replace('Master Guide — ', '').strip()
    hub = ''
    stats: dict = {}
    html = site_render.render_document(md_text, title=title, hub=hub, when=when, max_images=10 ** 9, max_charts=10 ** 9, scrub_stats=scrub_stats, unwrap_all_links=scrub_stats is None, data_not_captured='DATA NOT CAPTURED' in md_text, drop_heading=not a.title, stats=stats, theme=a.theme)
    for stale in out.glob('*.html'):
        stale.unlink()
    (out / 'index.html').write_text(html)
    guard = {'ok': False, 'checks': {}}
    try:
        from site_guardrails import check_site
        guard = check_site(out)
        n_ok = sum((1 for c in guard['checks'].values() if c['pass']))
        print(f"  guardrails: {n_ok}/{len(guard['checks'])} checks passed — {('OK' if guard['ok'] else 'FAILED')}")
        for name, chk in guard['checks'].items():
            if not chk['pass']:
                print(f"    ✗ {name}: {chk['note']}")
        (out / 'guardrails.json').write_text(__import__('json').dumps(guard, indent=1))
    except Exception as ge:
        print(f'  guardrails: gate error (non-fatal): {ge}')
    print(f'✓ site written: {out}')
    print(f"  pages: 1 flowing guide ({stats['sections']} numbered parts, {stats['collapsed']} exact-duplicate blocks collapsed)")
    print(f"  images: found={img_report['found']} downloaded={img_report['downloaded']} failed_or_kept_remote={img_report['failed_or_kept_remote']} skipped_nontopical={img_report['skipped_nontopical']} gated_kept={stats['kept']} gated_dropped={stats['dropped']}")
    print(f"  charts: {stats['charts']} teaching charts from {stats['rows']} data rows (source tables kept in-page)")
    if stats['limitations']:
        print(f"  research-limitations block rendered ({stats['limitations']} items)")
    return 0
if __name__ == '__main__':
    try:
        import markdown
    except ImportError:
        sys.exit('python markdown module required (pip install markdown)')
    sys.exit(render())