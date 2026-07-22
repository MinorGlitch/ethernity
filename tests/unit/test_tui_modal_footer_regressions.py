from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.widgets import Footer, Static

from ethernity.app.screens.confirm_action import ConfirmActionScreen
from ethernity.app.screens.diagnostics import DiagnosticsScreen
from ethernity.app.screens.edit_field import EditFieldScreen
from ethernity.app.screens.file_picker import FilePickerScreen
from ethernity.app.screens.help import HelpScreen
from ethernity.app.screens.modal import EthernityModalScreen
from ethernity.app.screens.paste_text import PasteTextScreen
from ethernity.app.screens.review_task import ReviewTaskScreen
from ethernity.app.screens.task_result import TaskResultScreen


class FooterTestApp(App[None]):
    def compose(self) -> ComposeResult:
        yield Static("Main screen")
        yield Footer()


def _confirmation(title: str) -> ConfirmActionScreen:
    return ConfirmActionScreen(title=title, message="Continue?", confirm_label="Confirm")


def test_all_app_modal_screens_share_footer_lifecycle() -> None:
    screen_types = (
        ConfirmActionScreen,
        DiagnosticsScreen,
        EditFieldScreen,
        FilePickerScreen,
        HelpScreen,
        PasteTextScreen,
        ReviewTaskScreen,
        TaskResultScreen,
    )

    assert all(issubclass(screen_type, EthernityModalScreen) for screen_type in screen_types)


def test_footer_stays_hidden_until_nested_modals_are_closed() -> None:
    async def run() -> None:
        app = FooterTestApp()

        async with app.run_test() as pilot:
            footer = app.query_one(Footer)
            assert footer.display

            first_modal = _confirmation("First")
            await app.push_screen(first_modal)
            await pilot.pause()
            assert not footer.display

            second_modal = _confirmation("Second")
            await app.push_screen(second_modal)
            await pilot.pause()
            assert app.screen is second_modal
            assert not footer.display

            second_modal.dismiss(False)
            await pilot.pause()
            assert app.screen is first_modal
            assert not footer.display

            first_modal.dismiss(False)
            await pilot.pause()
            assert len(app.screen_stack) == 1
            assert footer.display

    asyncio.run(run())
