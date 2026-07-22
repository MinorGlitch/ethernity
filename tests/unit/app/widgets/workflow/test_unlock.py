"""Unlock editor behavior."""

import asyncio

from textual.widgets import RadioSet

from ethernity.app.widgets.workflow.unlock import UnlockEditor
from ethernity.tasks.presentation.models import (
    ChoicePresentation,
    UnlockBodyPresentation,
    WorkspaceAction,
)
from tests.unit.app.widgets.workflow.helpers import PrimitiveHarness


def test_unlock_editor_uses_native_radio_behavior_and_typed_local_action() -> None:
    async def run() -> None:
        editor = UnlockEditor(
            UnlockBodyPresentation(
                methods=(
                    ChoicePresentation("passphrase", "Passphrase", selected=True),
                    ChoicePresentation("sheets", "Recovery sheets"),
                    ChoicePresentation("payloads", "Recovery payload files"),
                ),
                contextual_action=WorkspaceAction("enter-unlock", "Enter passphrase..."),
                material_summary="Passphrase set",
            ),
            id="unlock",
        )
        app = PrimitiveHarness(editor)
        async with app.run_test(size=(80, 24)) as pilot:
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
