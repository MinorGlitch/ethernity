from __future__ import annotations

import asyncio

from textual.widgets import Button, ListView

from ethernity.app.application import EthernityApp
from ethernity.app.screens.confirm_action import ConfirmActionScreen


def test_narrow_drawer_traversal_closes_and_restores_its_invoker() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("2")
            await pilot.pause()

            source_methods = app.query_one("#workflow-restore-source-body-methods")
            source_methods.focus()
            await pilot.pause()

            for close_key in ("tab", "shift+tab", "escape"):
                await pilot.press("h")
                await pilot.pause()

                assert app._nav_drawer_open
                assert app.screen.focused is app.query_one("#nav-list", ListView)
                assert not app.query_one("#canvas-task-workspaces").has_focus_within

                await pilot.press(close_key)
                await pilot.pause()

                assert not app._nav_drawer_open
                assert app.screen.focused is source_methods

            await pilot.click("#nav-strip")
            await pilot.pause()
            assert app._nav_drawer_open

            await pilot.press("tab")
            await pilot.pause()

            assert not app._nav_drawer_open
            assert app.screen.focused is app.query_one("#nav-strip", Button)

    asyncio.run(run())


def test_narrow_drawer_selection_leaves_focus_in_a_coherent_workflow() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("2")
            await pilot.pause()
            source_header = app.query_one("#workflow-restore-source-header")
            source_header.focus()
            await pilot.pause()

            await pilot.press("left")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            assert app.active_task == "restore"
            assert not app._nav_drawer_open
            assert app.screen.focused is source_header

            await pilot.press("left")
            await pilot.pause()
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.pause()

            assert app.active_task == "add_files"
            assert not app._nav_drawer_open
            assert app.screen.focused is app.query_one(
                "#workflow-add_files-source-body-source-methods"
            )

    asyncio.run(run())


def test_tab_remains_canonical_for_guided_controls_and_modal_actions() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("2")
            await pilot.pause()
            source_methods = app.query_one("#workflow-restore-source-body-methods")
            source_methods.focus()
            await pilot.pause()

            await pilot.press("tab")
            await pilot.pause()

            guided_focus = app.screen.focused
            assert guided_focus is not None
            assert guided_focus is not source_methods
            assert guided_focus.has_class("workspace-control")
            assert app.query_one("#canvas-task-workspaces").has_focus_within

            await pilot.press("shift+tab")
            await pilot.pause()
            assert app.screen.focused is source_methods

            await pilot.press("h")
            await pilot.pause()
            assert app._nav_drawer_open

            confirm_screen = ConfirmActionScreen(
                title="Confirm action",
                message="Continue?",
                confirm_label="Delete",
            )
            await app.push_screen(confirm_screen)
            await pilot.pause()
            assert app.screen.focused is confirm_screen.query_one("#confirm-action-cancel", Button)

            await pilot.press("tab")
            await pilot.pause()
            assert app.screen.focused is confirm_screen.query_one("#confirm-action-confirm", Button)
            assert app._nav_drawer_open

            await pilot.press("shift+tab")
            await pilot.pause()
            assert app.screen.focused is confirm_screen.query_one("#confirm-action-cancel", Button)
            assert app._nav_drawer_open

            await pilot.press("escape")
            await pilot.pause()
            assert app.screen is app.screen_stack[0]
            assert app._nav_drawer_open

            await pilot.press("tab")
            await pilot.pause()
            assert not app._nav_drawer_open
            assert app.screen.focused is source_methods

    asyncio.run(run())
