"""Direct document loading and decoded-source presentation."""

import asyncio
from dataclasses import replace

from textual.widgets import Button, RadioSet, Static

from ethernity.app.widgets.workflow.source import SourceChooser
from ethernity.tasks.presentation.models import SourceAssessmentPresentation, WorkspaceAction
from tests.unit.app.widgets.workflow.widget_harness import (
    WorkflowWidgetHarness,
    sample_source_body,
)


def test_source_chooser_loads_documents_without_classifying_them() -> None:
    async def run() -> None:
        chooser = SourceChooser(sample_source_body(), id="source")
        app = WorkflowWidgetHarness(chooser)
        async with app.run_test(size=(80, 24)) as pilot:
            assert not chooser.query(RadioSet)
            primary = chooser.query_one("#source-load", Button)
            assert str(primary.label) == "Load backup documents..."
            primary.focus()
            await pilot.press("enter")
            await pilot.pause()
            assert app.source_actions == ["load"]

            await pilot.click("#source-secondary-0")
            await pilot.pause()
            await pilot.click("#source-secondary-1")
            await pilot.pause()
            assert app.source_actions == ["load", "text", "payloads"]

    asyncio.run(run())


def test_source_chooser_keeps_decoded_details_visible_when_changing_documents() -> None:
    async def run() -> None:
        body = replace(
            sample_source_body(),
            assessment=SourceAssessmentPresentation(
                source_kind="scanned_pages",
                source_label="Backup documents",
                source_summary="family-backup.pdf",
                backup_identity="1234abcd",
                version_summary="1 backup document found",
                document_summary="1 complete backup document; authentication found for 1",
                unlock_summary="Recovery sheets ready: 2 validated.",
            ),
            primary_action=WorkspaceAction("change", "Change documents..."),
        )
        chooser = SourceChooser(body, id="source")
        app = WorkflowWidgetHarness(chooser)
        async with app.run_test(size=(80, 24)) as pilot:
            assessment = chooser.query_one(".guided-summary")
            assert assessment.display
            details = [str(widget.content) for widget in assessment.query(Static)]
            assert "Backup 1234abcd" in details
            assert "Recovery sheets ready: 2 validated." in details

            await pilot.click("#source-load")
            await pilot.pause()
            assert app.source_actions == ["change"]
            assert assessment.display

    asyncio.run(run())


def test_source_chooser_loading_state_explains_what_is_happening() -> None:
    async def run() -> None:
        chooser = SourceChooser(replace(sample_source_body(), loading=True), id="source")
        app = WorkflowWidgetHarness(chooser)
        async with app.run_test(size=(80, 24)) as pilot:
            assert chooser.query_one(".guided-loading").display
            label = chooser.query_one(".guided-loading-label", Static)
            assert str(label.content) == "Reading backup documents..."
            assert chooser.query_one(".guided-source-actions").disabled
            await pilot.click("#source-load")
            await pilot.pause()
            assert app.source_actions == []

    asyncio.run(run())
