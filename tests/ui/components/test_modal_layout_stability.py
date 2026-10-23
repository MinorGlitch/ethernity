from __future__ import annotations

import asyncio

import pytest
from textual.widgets import Button, Footer, Static

from ethernity.app.application import EthernityApp
from ethernity.app.screens.confirm_action import ConfirmActionScreen
from ethernity.app.screens.help import HelpScreen
from tests.support.app import run_app_test


@pytest.mark.parametrize("size", ((60, 20), (80, 24), (120, 32)))
def test_help_and_nested_dialogs_keep_the_workspace_geometry(size: tuple[int, int]) -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=size) as pilot:
            main = app.screen
            selectors = ("#app-shell", "#workspace", "#task-action-bar", "#canvas-primary")
            before = {selector: main.query_one(selector).region for selector in selectors}
            assert before["#app-shell"].height == size[1]
            help_button = main.query_one("#nav-help", Button)
            assert main.query_one("#workbench-navigation").content_region.contains_region(
                help_button.region
            )

            await pilot.click(help_button)
            help_screen = app.screen
            assert isinstance(help_screen, HelpScreen)
            shortcuts = str(help_screen.query_one("#help-shortcuts", Static).content)
            assert all(
                shortcut in shortcuts for shortcut in ("Ctrl+B", "Ctrl+P", "?: Help", "q: Quit")
            )
            assert main.query_one("#workspace").region == before["#workspace"]

            confirmation = ConfirmActionScreen(
                title="Test dialog",
                message="Close this dialog to return to Help.",
                confirm_label="OK",
            )
            await app.push_screen(confirmation)
            await pilot.pause()
            assert all(not screen.query(Footer) for screen in app.screen_stack)
            assert {selector: main.query_one(selector).region for selector in selectors} == before
            help_region = help_screen.query_one("#help-modal").region

            await pilot.press("escape")
            assert app.screen is help_screen
            assert help_screen.query_one("#help-modal").region == help_region
            await pilot.click("#help-close")
            assert app.screen is main
            assert {selector: main.query_one(selector).region for selector in selectors} == before

            await pilot.press("?")
            assert isinstance(app.screen, HelpScreen)
            await pilot.press("escape")
            assert app.screen is main
            assert main.query_one("#workspace").region == before["#workspace"]

    asyncio.run(run())
