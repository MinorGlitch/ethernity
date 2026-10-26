from __future__ import annotations

import asyncio
from itertools import combinations

import pytest
from textual.widgets import Button

from ethernity.app.application import EthernityApp
from ethernity.app.widgets.navigation import NavigationBar
from tests.support.app import run_app_test


@pytest.mark.parametrize("height", [20, 32])
def test_navigation_fits_full_labels_and_settles_after_resize(height: int) -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, height)) as pilot:
            navigation = app.query_one(NavigationBar)
            buttons = list(navigation.query(Button))
            for width in (60, 61, 62, 40, 32, 80, 109, 110, 120, 60):
                await pilot.resize_terminal(width, height)
                regions = [button.region for button in buttons]
                assert all(navigation.content_region.contains_region(region) for region in regions)
                assert all(not left.overlaps(right) for left, right in combinations(regions, 2))
                assert all(
                    str(button.label) in button.render_line(button.content_size.height // 2).text
                    for button in buttons
                )
                assert len({region.y for region in regions}) == (
                    3 if width == 32 else 2 if width == 40 else 1
                )
                assert app.query_one("#workspace").region.y >= navigation.region.bottom

                layouts = []
                app.screen.screen_layout_refresh_signal.subscribe(app, layouts.append)
                for _ in range(2):
                    navigation.reflow()
                    await pilot.pause()
                assert not layouts
                app.screen.screen_layout_refresh_signal.unsubscribe(app)

    asyncio.run(run())


def test_wrapped_navigation_keeps_mouse_and_keyboard_access() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(60, 20)) as pilot:
            for selector, task in (
                ("#nav-kit", "kit"),
                ("#nav-settings", "settings"),
                ("#nav-restore", "restore"),
                ("#nav-create", "backup"),
            ):
                assert await pilot.click(selector)
                assert app.active_task == task
                await pilot.press("ctrl+b")
                assert app.focused is app.query_one(selector)

            await pilot.press("right", "right", "right")
            assert app.focused is app.query_one("#nav-kit")
            await pilot.press("enter")
            assert app.active_task == "kit"

            assert await pilot.click("#nav-manage")
            assert app._nav_menu_open
            assert (
                app.query_one("#nav-menu").region.y
                >= app.query_one(NavigationBar).content_region.bottom
            )
            await pilot.press("enter")
            assert app.active_task == "add_files"
            assert not app._nav_menu_open

    asyncio.run(run())
