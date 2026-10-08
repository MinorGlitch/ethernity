"""Unlock editor behavior."""

import asyncio

from textual.widgets import Input, RadioSet

from ethernity.app.widgets.workflow.unlock import UnlockEditor
from ethernity.tasks.presentation.models import (
    ChoicePresentation,
    UnlockBodyPresentation,
    WorkspaceAction,
)
from tests.support.app import run_app_test
from tests.unit.app.widgets.workflow.widget_harness import WorkflowWidgetHarness


def test_unlock_editor_uses_native_radio_behavior_and_typed_local_action() -> None:
    async def run() -> None:
        editor = UnlockEditor(
            UnlockBodyPresentation(
                methods=(
                    ChoicePresentation("passphrase", "Passphrase", selected=True),
                    ChoicePresentation("sheets", "Recovery sheets"),
                    ChoicePresentation("payloads", "Recovery payload files"),
                ),
                method_action=WorkspaceAction("enter-unlock", "Enter passphrase..."),
                input_summary="Passphrase set",
            ),
            id="unlock",
        )
        app = WorkflowWidgetHarness(editor)
        async with run_app_test(app, size=(80, 24)) as pilot:
            radio = editor.query_one(RadioSet)
            radio.focus()

            await pilot.press("right", "space")
            await pilot.pause()

            assert editor.selected_method == "sheets"
            assert app.unlock_methods == ["sheets"]

            await pilot.click("#unlock-action")
            await pilot.pause()

            assert app.unlock_actions == ["enter-unlock"]

    asyncio.run(run())


def test_inline_passphrase_masks_input_and_commits_only_user_edits() -> None:
    async def run() -> None:
        editor = UnlockEditor(
            UnlockBodyPresentation(
                methods=(ChoicePresentation("passphrase", "Passphrase", selected=True),),
                passphrase_set=True,
                input_summary="Passphrase set",
            ),
            id="unlock",
        )
        app = WorkflowWidgetHarness(editor)
        async with run_app_test(app, size=(80, 24)) as pilot:
            value = editor.query_one(Input)
            assert value.password
            assert value.value == ""
            value.focus()
            await pilot.press("tab")
            await pilot.pause()
            assert app.unlock_values == []
            value.focus()
            await pilot.press(*"test-secret")
            await pilot.pause()
            assert "test-secret" not in value.render_line(0).text
            await pilot.press("enter")
            await pilot.pause()
            assert app.unlock_values == ["test-secret"]
            assert value.value == ""
            await pilot.press("tab")
            await pilot.pause()
            assert app.unlock_values == ["test-secret"]

    asyncio.run(run())
