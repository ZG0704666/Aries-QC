"""无头浏览器冒烟测试：真实点击接单、查看证据、裁定。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'runs' / '_ui_smoke'


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8877/')
    parser.add_argument('--demo', default='single')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, device_scale_factor=1)
        page = context.new_page()
        page.on('console', lambda msg: errors.append(f'console:{msg.type}:{msg.text}') if msg.type == 'error' else None)
        page.on('pageerror', lambda error: errors.append(f'pageerror:{error}'))
        page.goto(args.url, wait_until='networkidle')
        page.wait_for_timeout(800)
        page.screenshot(path=str(OUT / '01_welcome.png'), full_page=True)

        page.click(f'[data-demo="{args.demo}"]')
        page.wait_for_selector('#runView:not([hidden])', timeout=20000)
        page.wait_for_function(
            "() => /DONE|FAILED|NEEDS_INPUT/.test(document.querySelector('#runIdLabel').textContent)",
            timeout=180000,
        )
        page.wait_for_timeout(1200)
        page.screenshot(path=str(OUT / '02_overview.png'), full_page=True)

        for tab in ('tasks', 'classes', 'findings', 'recollect', 'fix', 'delivery'):
            page.click(f'button[data-tab="{tab}"]')
            page.wait_for_timeout(500)
            page.screenshot(path=str(OUT / f'03_{tab}.png'), full_page=True)

        row = page.query_selector('.finding-row[data-sample]:not([data-sample=""])')
        if row:
            row.click()
            page.wait_for_selector('#drawer:not([hidden])', timeout=10000)
            page.wait_for_timeout(900)
            page.screenshot(path=str(OUT / '04_drawer.png'), full_page=True)
            accept = page.query_selector('#drawer button[data-action="accept"]')
            if accept:
                accept.click()
                page.wait_for_timeout(900)
                page.screenshot(path=str(OUT / '05_adjudicated.png'), full_page=True)
            page.click('#drawerClose')

        page.click('button[data-tab="delivery"]')
        page.wait_for_timeout(600)
        page.screenshot(path=str(OUT / '06_delivery.png'), full_page=True)
        browser.close()
    print('screenshots:', OUT)
    if errors:
        print('JS ERRORS:')
        for item in errors:
            print(' -', item)
        return 1
    print('no JS errors')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())