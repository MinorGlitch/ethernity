"""Responsive controls must settle instead of feeding scrollbar changes back into layout."""

from __future__ import annotations

import asyncio

import pytest
from textual.app import ComposeResult
from textual.widgets import Button, Static

from ethernity.app.styling import StyledApp
from ethernity.app.widgets.actions import ActionButton, ResponsiveActions, inline_action_group
from ethernity.app.widgets.form import FormScroll
from tests.support.app import run_app_test


class ActionsApp(StyledApp):
    def compose(self) -> ComposeResult:
        with FormScroll(id="form"):
            yield inline_action_group(
                ActionButton("Load backup documents...", "load", variant="primary"),
                ActionButton("Paste text...", "paste"),
                ActionButton("Clear", "clear"),
            )
            yield Static("", id="extra-content")


@pytest.mark.parametrize("width", [64, 86, 100])
def test_scrollbar_changes_do_not_resize_or_rewrap_actions(width: int) -> None:
    async def run() -> None:
        app = ActionsApp()
        async with run_app_test(app, size=(width, 30)) as pilot:
            form = app.query_one(FormScroll)
            actions = app.query_one(ResponsiveActions)
            extra = app.query_one("#extra-content")
            assert not form.show_vertical_scrollbar
            original_size = actions.size
            button_sizes = tuple(button.size for button in actions.query(Button))
            for height in (40, 1, 40, 1):
                extra.styles.height = height
                await pilot.pause()
                assert form.show_vertical_scrollbar is (height == 40)
                assert actions.size == original_size
                assert tuple(button.size for button in actions.query(Button)) == button_sizes
                assert all(
                    button.region.right <= form.scrollable_content_region.right
                    for button in actions.query(Button)
                )

    asyncio.run(run())


def test_reflow_only_invalidates_layout_when_the_arrangement_changes() -> None:
    async def run() -> None:
        app = ActionsApp()
        async with run_app_test(app, size=(64, 30)) as pilot:
            actions = app.query_one(ResponsiveActions)
            primary = app.query_one("#load", Button)
            assert actions.styles.grid_size_columns == 2
            assert primary.styles.column_span == 2
            layouts = []
            app.screen.screen_layout_refresh_signal.subscribe(app, layouts.append)
            for _ in range(3):
                actions.reflow()
                await pilot.pause()
            assert not layouts

            await pilot.resize_terminal(100, 30)
            assert actions.styles.grid_size_columns == 3
            assert primary.styles.column_span == 1
            assert layouts

    asyncio.run(run())
