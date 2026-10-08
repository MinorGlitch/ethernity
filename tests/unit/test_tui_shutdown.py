"""Pending UI events must tolerate the screen being removed during shutdown."""

import asyncio

import pytest
from textual.widgets import ListItem, ListView, Select

from ethernity.app.application import EthernityApp


@pytest.mark.parametrize("pending", ["selection", "navigation", "focus"])
def test_pending_ui_work_does_not_access_closed_screens(monkeypatch, pending) -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test():
            select = app.query_one("#workspace-backup-paper-size", Select)
            with select.prevent(Select.Changed):
                select.value = "LETTER"
            selected = Select.Changed(select, "LETTER")
            navigation = ListView.Selected(
                app.query_one("#nav-list", ListView), app.query_one("#rebuild", ListItem), 1
            )
            close_all = app._close_all

            async def close_with_pending_event() -> None:
                await close_all()
                assert not app.is_running
                assert not app.screen_stack
                # Drain an event or refresh callback after its widgets have closed,
                # as can happen when shutdown overtakes the application queue.
                if pending == "selection":
                    await app.on_select_changed(selected)
                elif pending == "navigation":
                    await app.on_list_view_selected(navigation)
                else:
                    app._focus_active_task("backup")

            monkeypatch.setattr(app, "_close_all", close_with_pending_event)
        assert app.active_task == "backup"

    asyncio.run(run())
