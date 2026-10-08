"""Scrollbar spacing belongs to the shared skin, including native scrolling controls."""

from __future__ import annotations

import asyncio

import pytest
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import OptionList, RichLog, Static

from ethernity.app.styling import StyledApp
from ethernity.app.widgets.form import FormScroll
from tests.support.app import run_app_test
from tests.support.pilot import wait_for_condition


class ScrollbarApp(StyledApp):
    def compose(self) -> ComposeResult:
        # Equal, bounded hosts exercise both container and native-widget scrollbars.
        yield FormScroll(*(Static(f"Row {index}") for index in range(40)), id="form")
        yield VerticalScroll(
            *(Static(f"Row {index}") for index in range(40)), id="document", classes="document-body"
        )
        yield OptionList(*(f"Choice {index}" for index in range(40)), id="choices")


@pytest.mark.parametrize("size", [(120, 40), (60, 24)])
def test_scrollbars_keep_a_real_content_gap_and_remain_clickable(size) -> None:
    async def run() -> None:
        app = ScrollbarApp()
        async with run_app_test(app, size=size) as pilot:
            for host in app.query("#form, #document, #choices"):
                host.styles.height = 6
            await wait_for_condition(
                pilot,
                lambda: all(
                    host.region.height == 6 and host.region.width == app.screen.content_region.width
                    for host in app.query("#form, #document, #choices")
                ),
                "scroll hosts to fit the screen after resizing",
            )
            for host in app.query("#form, #document, #choices"):
                assert host.show_vertical_scrollbar
                bar = host.vertical_scrollbar
                assert bar.region.width == 3
                assert bar.content_region.width == 1
                assert bar.content_region.x - host.scrollable_content_region.right == 2
                if host.is_container:
                    assert all(
                        child.region.right <= bar.content_region.x - 2 for child in host.children
                    )
                # Track actions still work at the visible one-cell track.
                assert await pilot.click(bar, offset=(2, bar.region.height - 1))
                await wait_for_condition(
                    pilot,
                    lambda host=host: host.scroll_y > 0,
                    f"{host.id} scrollbar to move content",
                )
                host.scroll_home(animate=False, immediate=True)
                await pilot.pause()
                assert host.scroll_y == 0

    asyncio.run(run())


def test_native_log_keeps_horizontal_track_compact_and_vertical_gap_on_resize() -> None:
    class LogApp(StyledApp):
        def compose(self) -> ComposeResult:
            yield RichLog(id="log", wrap=False)

    async def run() -> None:
        app = LogApp()
        async with run_app_test(app, size=(80, 24)) as pilot:
            log = app.query_one(RichLog)
            log.styles.height = 10
            log.styles.width = 40
            for _ in range(30):
                log.write("Long log line " * 20)
            await pilot.pause()
            for size in ((80, 24), (60, 24), (120, 40)):
                await pilot.resize_terminal(*size)
                await pilot.pause()
                assert log.show_vertical_scrollbar
                assert log.show_horizontal_scrollbar
                vertical = log.vertical_scrollbar
                horizontal = log.horizontal_scrollbar
                assert vertical.content_region.width == 1
                assert vertical.content_region.x - log.scrollable_content_region.right == 2
                assert horizontal.region.height == horizontal.content_region.height == 1
                assert horizontal.styles.padding.left == 0
            assert await pilot.click(horizontal, offset=(horizontal.region.width - 1, 0))
            await wait_for_condition(pilot, lambda: log.scroll_x > 0, "log to scroll horizontally")

    asyncio.run(run())
