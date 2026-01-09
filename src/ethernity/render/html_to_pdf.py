#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright


def render_html_to_pdf(html: str, output_path: str | Path) -> None:
    output_path = Path(output_path)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="networkidle")
            page.emulate_media(media="print")
            page.pdf(
                path=str(output_path),
                print_background=True,
                prefer_css_page_size=True,
                margin={"top": "0mm", "right": "0mm", "bottom": "0mm", "left": "0mm"},
            )
        finally:
            browser.close()
