"""Path selection and destination editor behavior."""

import asyncio

from textual.widgets import SelectionList, Static

from ethernity.app.widgets.workflow.controls import InlineNotice
from ethernity.app.widgets.workflow.paths import DestinationEditor, PathSelectionEditor
from ethernity.tasks.presentation.models import (
    DestinationBodyPresentation,
    InlineNoticePresentation,
    PathItemPresentation,
    PathSelectionBodyPresentation,
    WorkspaceAction,
)
from tests.unit.app.widgets.workflow.helpers import PrimitiveHarness


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
        path_app = PrimitiveHarness(paths)
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
        destination_app = PrimitiveHarness(destination)
        async with destination_app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            value = destination.query_one(".guided-field-value", Static)
            notice = destination.query_one(InlineNotice)

            assert str(value.content) == "[red]/tmp/Recovered[/red]"
            assert "matching names may be replaced" in str(notice.content)

            await pilot.click("#destination-action")
            await pilot.pause()

            assert destination_app.destination_actions == ["browse"]

    asyncio.run(run())
