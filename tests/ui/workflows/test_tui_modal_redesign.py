from __future__ import annotations

import asyncio

import pytest
from textual.geometry import Region
from textual.widgets import Button, Input, MarkdownViewer, RichLog, Static, TextArea

from ethernity.app.application import EthernityApp
from ethernity.app.help_content import build_help_content
from ethernity.app.input_parsers import parse_threshold_count
from ethernity.app.screens.confirm_action import ConfirmActionScreen
from ethernity.app.screens.diagnostics import DiagnosticsScreen
from ethernity.app.screens.edit_field import EditFieldScreen
from ethernity.app.screens.help import HelpScreen
from ethernity.app.screens.paste_text import PasteTextScreen
from ethernity.tasks.models import TaskDiagnosticBlock, TaskDiagnostics
from tests.support.app import run_app_test
from tests.support.pilot import wait_for_condition, wait_for_widget


def _inside(outer: Region, inner: Region) -> bool:
    return (
        outer.x <= inner.x
        and outer.y <= inner.y
        and inner.right <= outer.right
        and inner.bottom <= outer.bottom
    )


@pytest.mark.portability
def test_editor_keeps_invalid_quorum_draft_until_validator_accepts_it() -> None:
    def quorum_error(value: str) -> str | None:
        if value and parse_threshold_count(value) is None:
            return "Use a quorum with at least one required sheet and enough total sheets."
        return None

    async def run() -> None:
        results: list[str | None] = []
        app = EthernityApp()
        async with run_app_test(app, size=(80, 24)) as pilot:
            screen = EditFieldScreen(
                title="Recovery sheets",
                prompt="Enter the required and total sheet counts.",
                mask_template="00/00",
                validator=quorum_error,
            )
            await app.push_screen(screen, results.append)
            await wait_for_widget(pilot, "#edit-field-input")
            field = screen.query_one("#edit-field-input", Input)
            field.value = "2/0"
            save = screen.query_one("#edit-field-save", Button)
            await wait_for_condition(pilot, lambda: save.disabled, "invalid quorum validation")

            assert screen.query_one("#edit-field-save", Button).disabled
            assert "enough total sheets" in str(
                screen.query_one("#edit-field-error", Static).content
            )
            await pilot.press("enter")
            assert app.screen is screen
            assert not results
            assert field.value.replace(" ", "") == "2/0"

            field.value = "2/3"
            await wait_for_condition(pilot, lambda: not save.disabled, "valid quorum validation")
            assert not screen.query_one("#edit-field-save", Button).disabled
            await pilot.press("enter")
            await wait_for_condition(pilot, lambda: bool(results), "accepted quorum")
            assert results == ["2/3"]

    asyncio.run(run())


def test_password_editor_masks_value_and_preserves_whitespace() -> None:
    async def run() -> None:
        results: list[str | None] = []
        app = EthernityApp()
        async with run_app_test(app, size=(80, 24)) as pilot:
            screen = EditFieldScreen(
                title="Passphrase",
                prompt="Enter a passphrase.",
                value="  actual phrase  ",
                password=True,
            )
            await app.push_screen(screen, results.append)
            await pilot.pause()
            field = screen.query_one("#edit-field-input", Input)
            assert field.password
            assert str(screen.query_one("#edit-field-save", Button).label) == "Apply"
            await pilot.press("enter")
            assert results == ["  actual phrase  "]

    asyncio.run(run())


def test_paste_editor_keeps_enter_for_newlines_and_saves_full_text() -> None:
    async def run() -> None:
        results: list[str | None] = []
        app = EthernityApp()
        async with run_app_test(app, size=(80, 24)) as pilot:
            screen = PasteTextScreen(title="Recovery text", prompt="Paste the whole document.")
            await app.push_screen(screen, results.append)
            await pilot.pause()
            field = screen.query_one("#paste-text-input", TextArea)
            assert str(screen.query_one("#paste-text-save", Button).label) == "Use text"
            field.load_text("first")
            field.move_cursor((0, 5))
            await pilot.press("enter")
            assert app.screen is screen
            assert field.text == "first\n"
            field.load_text("first\nsecond")
            await pilot.pause()
            await pilot.click("#paste-text-save")
            await pilot.pause()
            assert results == ["first\nsecond"]

    asyncio.run(run())


@pytest.mark.parametrize("size", ((60, 20), (80, 24)))
def test_help_diagnostics_and_input_modal_actions_stay_visible(size: tuple[int, int]) -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=size) as pilot:
            screens = (
                (EditFieldScreen(title="Name", prompt="Enter a name."), "edit-field"),
                (
                    PasteTextScreen(title="Recovery text", prompt="Paste the whole document."),
                    "paste-text",
                ),
                (HelpScreen(build_help_content(task="restore")), "help"),
                (
                    DiagnosticsScreen(
                        TaskDiagnostics(
                            title="Diagnostics",
                            blocks=(TaskDiagnosticBlock(title="Inputs", content='{"files": 3}'),),
                        )
                    ),
                    "diagnostics",
                ),
                (
                    ConfirmActionScreen(
                        title="Reset settings",
                        message="Replace saved defaults?",
                        confirm_label="Reset",
                    ),
                    "confirm-action",
                ),
            )
            viewport = Region(0, 0, *size)
            for screen, prefix in screens:
                await app.push_screen(screen)
                await pilot.pause()
                modal = screen.query_one(f"#{prefix}-modal")
                actions = screen.query_one(f"#{prefix}-actions")
                assert _inside(viewport, modal.region)
                assert _inside(modal.region, actions.region)
                for button in actions.query(Button):
                    assert _inside(actions.region, button.region)
                    assert button.region.height > 0
                screen.dismiss(None)
                await pilot.pause()

    asyncio.run(run())


def test_help_focuses_scroll_content_and_lists_real_navigation_commands() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(80, 24)) as pilot:
            screen = HelpScreen(build_help_content(task="restore"))
            await app.push_screen(screen)
            await pilot.pause()
            assert screen.focused is screen.query_one("#help-body", MarkdownViewer).document
            shortcuts = str(screen.query_one("#help-shortcuts", Static).content)
            assert "j/k: Navigate" in shortcuts
            assert "h/l: Switch pane" in shortcuts
            assert "Ctrl+R: Review" in shortcuts
            assert "Ctrl+P: Actions" in shortcuts

    asyncio.run(run())


def test_diagnostics_json_uses_wrapped_lines_at_small_terminal_width() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(60, 20)) as pilot:
            screen = DiagnosticsScreen(
                TaskDiagnostics(
                    title="Diagnostics",
                    blocks=(TaskDiagnosticBlock(title="Inputs", content='{ "files": 3 }'),),
                )
            )
            await app.push_screen(screen)
            await pilot.pause()
            log = screen.query_one("#diagnostics-log-0", RichLog)
            assert log.wrap
            assert not log.auto_scroll
            assert log.scroll_offset.y == 0
            assert len(log.lines) > 1
            assert log.has_focus

    asyncio.run(run())
