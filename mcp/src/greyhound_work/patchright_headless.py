from __future__ import annotations
import argparse
import sys
import time
from pathlib import Path

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, required=True)
    ap.add_argument('--profile', required=True)
    ap.add_argument('--headful', action='store_true', help='explicit opt-in; default is headless')
    a = ap.parse_args()
    try:
        from patchright.sync_api import sync_playwright
    except Exception as e:
        print(f'patchright unavailable: {e}', file=sys.stderr)
        return 2
    profile = Path(a.profile).expanduser()
    profile.mkdir(parents=True, exist_ok=True)
    argv = [f'--remote-debugging-port={a.port}', '--disable-blink-features=AutomationControlled', '--no-first-run', '--no-default-browser-check', '--disable-session-crashed-bubble', '--hide-crash-restore-bubble', '--no-pings', '--disable-crash-reporter', '--disable-component-update', '--disable-sync', '--disable-background-networking', '--disable-domain-reliability', '--disable-features=OptimizationHints,MediaRouter,Translate,OptimizationGuideFetchingForDesktop']
    pw = sync_playwright().start()
    launch_opts = dict(user_data_dir=str(profile), headless=not a.headful, viewport={'width': 1400, 'height': 1000}, java_script_enabled=True, locale='en-US', timezone_id='America/Phoenix', args=argv)
    try:
        ctx = pw.chromium.launch_persistent_context(channel='chromium', **launch_opts)
    except Exception:
        try:
            ctx = pw.chromium.launch_persistent_context(**{**launch_opts, 'args': launch_opts['args'] + ['--headless=new']})
        except Exception as e:
            print(f'launch failed: {e}', file=sys.stderr)
            return 3
    print(f'greyhound slot browser ready: port={a.port} profile={profile} headless={not a.headful}', flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        return 0
if __name__ == '__main__':
    sys.exit(main())