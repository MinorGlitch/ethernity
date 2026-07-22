"""Quorum and options editor behavior."""

import asyncio
from dataclasses import replace

import pytest
from textual.widgets import Input, Select, Static

from ethernity.app.widgets.workflow.controls import InlineNotice
from ethernity.app.widgets.workflow.options import OptionsEditor, QuorumEditor
from ethernity.tasks.presentation.models import (
    OptionsBodyPresentation,
    QuorumBodyPresentation,
    SelectFieldPresentation,
    SelectOptionPresentation,
    WorkspaceAction,
    WorkspaceValue,
)
from tests.unit.app.widgets.workflow.helpers import PrimitiveHarness


def test_quorum_editor_has_live_sentence_and_specific_inline_error() -> None:
    async def run() -> None:
        editor = QuorumEditor(
            QuorumBodyPresentation(threshold=3, count=5),
            id="quorum",
        )
        app = PrimitiveHarness(editor)
        async with app.run_test(size=(80, 24)) as pilot:
            summary = editor.query_one(".guided-summary", Static)
            notice = editor.query_one(InlineNotice)
            threshold = editor.query_one("#quorum-threshold", Input)
            count = editor.query_one("#quorum-count", Input)

            assert str(summary.content) == "Create 5 sheets; any 3 can restore"
            assert not notice.display

            threshold.value = "6"
            await pilot.pause()

            assert str(summary.content) == "Choose a valid quorum"
            assert "cannot exceed" in str(notice.content)
            assert notice.has_class("notice-error")

            count.value = "7"
            await pilot.pause()

            assert str(summary.content) == "Create 7 sheets; any 6 can restore"
            assert not notice.display
            assert app.quorum_values[-1] == (6, 7)
            assert editor.region.bottom <= 24

    asyncio.run(run())


def test_options_editor_uses_native_keyed_selects_and_suppresses_sync_messages() -> None:
    async def run() -> None:
        paper = SelectFieldPresentation(
            "workspace-rebuild-paper",
            "Paper [size]",
            (
                SelectOptionPresentation("A4", "[bold]A4[/bold]"),
                SelectOptionPresentation("LETTER", "Letter"),
            ),
            value="A4",
            allow_blank=False,
        )
        body = OptionsBodyPresentation(
            values=(
                WorkspaceValue("empty", "Empty", ""),
                WorkspaceValue("layout", "Layout", "[bold]A4[/bold]"),
            ),
            selects=(paper,),
            actions=(WorkspaceAction("hidden-action", "Hidden", visible=False),),
        )
        editor = OptionsEditor(body, id="options")
        app = PrimitiveHarness(editor)
        async with app.run_test(size=(80, 24)) as pilot:
            select = editor.query_one("#workspace-rebuild-paper", Select)
            values = list(editor.query(".guided-detail"))

            assert select.value == "A4"
            assert not values[0].display
            assert "[bold]A4[/bold]" in str(values[1].content)
            assert not editor.query_one(".guided-actions").display
            assert "[bold]A4[/bold]" in str(select._options[0][0])
            assert "[bold]A4[/bold]" in str(
                select.query_one("SelectCurrent > #label", Static).content
            )

            select.value = "LETTER"
            await pilot.pause()

            assert app.option_selects == [("workspace-rebuild-paper", "LETTER")]

            updated = replace(
                body,
                selects=(
                    replace(
                        paper,
                        value="A4",
                        options=(
                            SelectOptionPresentation("A4", "A4 updated"),
                            SelectOptionPresentation("LETTER", "Letter updated"),
                        ),
                    ),
                ),
            )
            editor.sync_presentation(updated)
            await pilot.pause()

            assert select.value == "A4"
            assert app.option_selects == [("workspace-rebuild-paper", "LETTER")]
            assert "A4 updated" in str(select._options[0][0])
            assert "A4 updated" in str(select.query_one("SelectCurrent > #label", Static).content)

            with pytest.raises(ValueError, match="choice keys cannot change"):
                editor.sync_presentation(
                    replace(
                        updated,
                        selects=(
                            replace(
                                updated.selects[0],
                                options=(SelectOptionPresentation("LEGAL", "Legal"),),
                                value="LEGAL",
                            ),
                        ),
                    )
                )

    asyncio.run(run())


def test_optional_options_part_hides_empty_chrome_but_keeps_structural_controls() -> None:
    async def run() -> None:
        empty = OptionsBodyPresentation(
            values=(WorkspaceValue("trust", "Trust", ""),),
            actions=(WorkspaceAction("accept", "Use these scans", visible=False),),
        )
        editor = OptionsEditor(empty, id="trust")
        app = PrimitiveHarness(editor)
        async with app.run_test(size=(80, 24)) as pilot:
            assert not editor.display
            assert not editor.query_one(".guided-detail").display
            assert not editor.query_one(".guided-actions").display

            editor.sync_presentation(
                replace(
                    empty,
                    values=(WorkspaceValue("trust", "Trust", "Confirmation required"),),
                    actions=(WorkspaceAction("accept", "Use these scans"),),
                )
            )
            await pilot.pause()

            assert editor.display
            assert editor.query_one(".guided-detail").display
            assert editor.query_one(".guided-actions").display

            await pilot.click("#accept")
            await pilot.pause()

            assert app.option_actions == ["accept"]

    asyncio.run(run())
