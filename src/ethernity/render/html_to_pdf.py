#!/usr/bin/env python3
# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

import atexit
from pathlib import Path
from typing import Mapping

from playwright.sync_api import Browser, Playwright, sync_playwright

_PLAYWRIGHT: Playwright | None = None
_BROWSER: Browser | None = None


def _shutdown_playwright() -> None:
    global _BROWSER, _PLAYWRIGHT
    browser = _BROWSER
    playwright = _PLAYWRIGHT
    _BROWSER = None
    _PLAYWRIGHT = None
    if browser is not None:
        browser.close()
    if playwright is not None:
        playwright.stop()


def _get_browser() -> Browser:
    global _BROWSER, _PLAYWRIGHT
    if _BROWSER is not None:
        return _BROWSER
    _PLAYWRIGHT = sync_playwright().start()
    _BROWSER = _PLAYWRIGHT.chromium.launch()
    atexit.register(_shutdown_playwright)
    return _BROWSER


def render_html_to_pdf(
    html: str,
    output_path: str | Path,
    *,
    resources: Mapping[str, tuple[str, bytes]] | None = None,
) -> None:
    output_path = Path(output_path)
    browser = _get_browser()
    page = browser.new_page()
    try:
        if resources:
            page.route(
                "https://ethernity.local/**",
                lambda route, request: _route_resource(route, request, resources),
            )
        page.set_content(html, wait_until="networkidle")
        page.emulate_media(media="print")
        page.pdf(
            path=str(output_path),
            print_background=True,
            prefer_css_page_size=True,
            margin={"top": "0mm", "right": "0mm", "bottom": "0mm", "left": "0mm"},
        )
    finally:
        page.close()


def _route_resource(route, request, resources: Mapping[str, tuple[str, bytes]]) -> None:
    entry = resources.get(request.url)
    if entry is None:
        route.fulfill(status=404, body=b"")
        return
    content_type, body = entry
    route.fulfill(
        status=200,
        body=body,
        content_type=content_type,
        headers={"Cache-Control": "no-store"},
    )
