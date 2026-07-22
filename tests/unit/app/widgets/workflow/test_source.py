"""Source chooser behavior."""

import asyncio
from dataclasses import replace

from textual.widgets import RadioButton, RadioSet, Static

from ethernity.app.widgets.workflow.source import SourceChooser
from ethernity.tasks.presentation.models import (
    SourceAssessmentPresentation,
    SourceBodyPresentation,
    WorkspaceAction,
)
from tests.unit.app.widgets.workflow.helpers import PrimitiveHarness, make_source_body


def test_source_chooser_uses_native_radio_set_and_can_return_to_no_selection() -> None:
    async def run() -> None:
        body = make_source_body()
        chooser = SourceChooser(body, id="source")
        app = PrimitiveHarness(chooser)
        async with app.run_test(size=(80, 24)) as pilot:
            radio = chooser.query_one(RadioSet)
            assert chooser.selected_method is None

            radio.focus()
            await pilot.press("space")
            await pilot.pause()

            assert chooser.selected_method == "scans"
            assert app.source_methods == ["scans"]

            chooser.sync_presentation(body)
            await pilot.pause()

            assert chooser.selected_method is None
            assert app.source_methods == ["scans"]

    asyncio.run(run())


def test_source_chooser_change_returns_to_all_methods_without_dispatching_old_action() -> None:
    async def run() -> None:
        body = SourceBodyPresentation(
            methods=make_source_body(selected="scans").methods,
            assessment=SourceAssessmentPresentation(
                source_kind="scanned_pages",
                source_label="Scanned pages",
                material_summary="4 pages",
            ),
            change_action=WorkspaceAction("change-source", "Change source..."),
        )
        chooser = SourceChooser(body, id="source")
        app = PrimitiveHarness(chooser)
        async with app.run_test(size=(80, 24)) as pilot:
            methods = chooser.query_one(RadioSet)
            assessment = chooser.query_one(".guided-summary")

            assert not methods.display
            assert assessment.display

            await pilot.click("#source-change")
            await pilot.pause()

            assert methods.display
            assert not assessment.display
            assert chooser.selected_method is None
            assert app.source_methods == []

            radio_buttons = list(methods.query(RadioButton))
            radio_buttons[2].value = True
            await pilot.pause()

            assert app.source_methods == ["text"]
            assert not methods.display
            assert assessment.display

    asyncio.run(run())


def test_source_chooser_loading_state_explains_what_is_happening() -> None:
    async def run() -> None:
        chooser = SourceChooser(replace(make_source_body(), loading=True), id="source")
        app = PrimitiveHarness(chooser)
        async with app.run_test(size=(80, 24)):
            loading = chooser.query_one(".guided-loading")
            label = chooser.query_one(".guided-loading-label", Static)

            assert loading.display
            assert str(label.content) == "Inspecting backup source..."
            assert not chooser.query_one(RadioSet).display

    asyncio.run(run())
