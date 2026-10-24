from __future__ import annotations

import asyncio

import pytest
from textual.widgets import Button

from ethernity.app.application import EthernityApp
from ethernity.app.screens.paste_text import PasteTextScreen
from ethernity.app.widgets.recovery_text import RecoveryTextArea
from tests.support.app import run_app_test


@pytest.mark.parametrize("theme", ["ethernity-dark", "ethernity-light"])
def test_recovery_entry_highlights_without_changing_typing_and_tidy_is_undoable(theme) -> None:
    async def run() -> None:
        results = []
        app = EthernityApp()
        async with run_app_test(app, size=(80, 24)) as pilot:
            app.theme = theme
            original = "01. ybnr\t fghj  1934\n02. kmnp @"
            screen = PasteTextScreen(
                title="Recovery text", prompt="Enter the printed text.", value=original
            )
            await app.push_screen(screen, results.append)
            await pilot.pause()
            field = screen.query_one(RecoveryTextArea)
            assert field.show_line_numbers
            assert field.text == original
            line = field.get_line(0)
            assert line.plain == original.splitlines()[0]
            assert line.get_style_at_offset(app.console, 0).strike
            assert line.get_style_at_offset(app.console, 4) != line.get_style_at_offset(
                app.console, 10
            )
            assert field.get_line(1).get_style_at_offset(app.console, 9).underline
            field.move_cursor((1, 10))
            await pilot.press("enter", "y", "b", "n", "r")
            typed = original + "\nybnr"
            assert field.text == typed
            await pilot.click("#paste-text-tidy")
            assert field.text == "ybnr fghj 1934\nkmnp @\nybnr"
            await pilot.press("ctrl+z")
            assert field.text == typed
            await pilot.click("#paste-text-save")
            assert results == ["ybnr fghj 1934\nkmnp @\nybnr"]

    asyncio.run(run())


def test_cancel_does_not_save_cleanup_and_clear_removes_the_draft() -> None:
    async def run() -> None:
        results = []
        app = EthernityApp()
        async with run_app_test(app, size=(60, 20)) as pilot:
            for action, expected in (("cancel", None), ("clear", "")):
                screen = PasteTextScreen(
                    title="Recovery text", prompt="Enter text.", value="01. ybnr"
                )
                await app.push_screen(screen, results.append)
                await pilot.pause()
                await pilot.click("#paste-text-tidy")
                button = screen.query_one(f"#paste-text-{action}", Button)
                assert button.region.bottom <= screen.size.height
                await pilot.click(button)
                assert results[-1] == expected

    asyncio.run(run())
