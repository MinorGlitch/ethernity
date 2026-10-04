"""Path selection and destination editor behavior."""

import asyncio
from dataclasses import replace

from textual.widgets import Input, SelectionList

from ethernity.app.widgets.workflow.controls import InlineNotice
from ethernity.app.widgets.workflow.paths import DestinationEditor, PathSelectionEditor
from ethernity.tasks.presentation.models import (
    DestinationBodyPresentation,
    InlineNoticePresentation,
    PathItemPresentation,
    PathSelectionBodyPresentation,
    WorkspaceAction,
)
from tests.unit.app.widgets.workflow.widget_harness import WorkflowWidgetHarness


def test_path_and_destination_summaries_render_dynamic_text_literally() -> None:
    async def run() -> None:
        paths = PathSelectionEditor(
            PathSelectionBodyPresentation(
                items=(
                    PathItemPresentation(
                        "one",
                        "archive.txt",
                        "[red]/tmp/archive.txt[/red]",
                        selected=True,
                    ),
                ),
                count_summary="1 file selected",
                actions=(WorkspaceAction("remove", "Remove selected"),),
            ),
            id="paths",
        )
        path_app = WorkflowWidgetHarness(paths)
        async with path_app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            selection = paths.query_one(SelectionList)
            assert paths.selected_keys == ("one",)
            assert "[red]/tmp/archive.txt[/red]" in str(selection.get_option_at_index(0).prompt)

            await pilot.click("#remove")
            await pilot.pause()

            assert path_app.path_actions == ["remove"]

        destination = DestinationEditor(
            DestinationBodyPresentation(
                display_path="[red]/tmp/Recovered[/red]",
                action=WorkspaceAction("browse", "Browse..."),
                notice=InlineNoticePresentation(
                    "Destination contains 2 items; matching names may be replaced.",
                    tone="warning",
                ),
            ),
            id="destination",
        )
        destination_app = WorkflowWidgetHarness(destination)
        async with destination_app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            value = destination.query_one(Input)
            notice = destination.query_one(InlineNotice)

            assert value.value == "[red]/tmp/Recovered[/red]"
            assert "matching names may be replaced" in str(notice.content)

            await pilot.click("#destination-action")
            await pilot.pause()

            assert destination_app.destination_actions == ["browse"]

    asyncio.run(run())


def test_destination_commits_typed_path_once_and_preserves_pending_edits() -> None:
    async def run() -> None:
        presentation = DestinationBodyPresentation(display_path="/tmp/original")
        destination = DestinationEditor(presentation, id="destination")
        app = WorkflowWidgetHarness(destination)
        async with app.run_test(size=(80, 24)) as pilot:
            value = destination.query_one(Input)
            value.focus()
            await pilot.press("ctrl+a", "ctrl+k")
            await pilot.press(*"~/Recovered")
            await pilot.pause()
            destination.sync_presentation(presentation)
            assert value.value == "~/Recovered"
            await pilot.press("enter")
            await pilot.pause()
            assert app.destination_values == ["~/Recovered"]
            assert value.value == "~/Recovered"
            destination.sync_presentation(replace(presentation, display_path="~/Recovered"))
            await pilot.press("enter")
            await pilot.pause()
            assert app.destination_values == ["~/Recovered"]

    asyncio.run(run())


def test_destination_sync_reveals_the_path_tail_and_preserves_the_edit_cursor() -> None:
    async def run() -> None:
        path = "/private/var/folders/very-long-generated-directory/backup-documents"
        presentation = DestinationBodyPresentation(display_path=path)
        destination = DestinationEditor(presentation, id="destination")
        app = WorkflowWidgetHarness(destination)
        async with app.run_test(size=(80, 24)) as pilot:
            value = destination.query_one(Input)
            assert value.value == path
            assert value.cursor_position == len(path)

            value.cursor_position = 4
            destination.sync_presentation(presentation)
            assert value.cursor_position == 4

            value.value = "/tmp/unfinished-folder"
            value.cursor_position = 5
            await pilot.pause()
            destination.sync_presentation(replace(presentation, display_path="/tmp/changed"))
            assert value.value == "/tmp/unfinished-folder"
            assert value.cursor_position == 5
            assert app.destination_values == []

    asyncio.run(run())
