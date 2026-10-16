from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.widgets import Select, SelectionList

from ethernity.app.application import EthernityApp
from ethernity.app.screens.file_picker import FilePickerMode, FilePickerScreen
from ethernity.app.widgets.workbench import WorkbenchSteps
from ethernity.app.widgets.workflow.steps import WorkflowStepStack
from ethernity.app.workflow_registry import build_guided_workflow
from ethernity.app.workflow_state import WorkflowUiState
from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.presentation.models import (
    CompositeBodyPresentation,
    OptionsBodyPresentation,
    SummaryPresentation,
)
from ethernity.tasks.rebuild import RebuildTaskState
from tests.support.app import run_app_test
from tests.support.pilot import click_when_ready, wait_for_condition, wait_for_widget


@pytest.mark.parametrize("output_dir", [None, Path("custom-update")])
def test_add_files_output_step_accepts_automatic_and_custom_destinations(
    output_dir: Path | None,
) -> None:
    state = AddFilesTaskState(
        source_paths=[Path("backup")],
        allow_stale_head=True,
        input_paths=[Path("notes.txt")],
        passphrase="secret",
        output_dir=output_dir,
    )
    workflow = build_guided_workflow(
        task="add_files",
        state=state,
        validation=state.validate_task(),
        ui_state=WorkflowUiState.start("source", "files", "unlock", "output"),
        review_summary=_empty_summary(),
        review_label="Review update",
    )

    assert workflow is not None
    assert [step.state for step in workflow.steps] == [
        "current",
        "complete",
        "complete",
        "complete",
    ]
    assert state.validate_task().ready
    assert state.to_add_files_request().output_dir == (
        str(output_dir) if output_dir is not None else None
    )
    output_section = next(section for section in state.sections() if section.key == "output")
    assert output_section.summary == (
        "Automatic folder in the current directory" if output_dir is None else str(output_dir)
    )


def test_rebuild_output_uses_typed_native_layout_selects() -> None:
    state = RebuildTaskState(
        backup_folder=Path("backup"),
        allow_stale_head=True,
        passphrase="secret",
        output_dir=Path("rebuilt"),
        paper_size="LETTER",
        design="forge",
    )
    workflow = build_guided_workflow(
        task="rebuild",
        state=state,
        validation=state.validate_task(),
        ui_state=WorkflowUiState.start("source", "unlock", "output"),
        review_summary=_empty_summary(),
        review_label="Review rebuild",
    )

    assert workflow is not None
    output = workflow.steps[-1].body
    assert isinstance(output, CompositeBodyPresentation)
    layout = output.parts[1].body
    assert isinstance(layout, OptionsBodyPresentation)
    assert [(field.key, field.value) for field in layout.selects] == [
        ("workspace-rebuild-paper", "LETTER"),
        ("workspace-rebuild-design", "forge"),
    ]


def test_add_files_path_selection_can_remove_one_item_without_reopening_picker() -> None:
    async def run() -> None:
        app = EthernityApp(
            add_files_state=AddFilesTaskState(
                source_paths=[Path("backup")],
                output_dir=Path("update-out"),
                allow_stale_head=True,
                input_paths=[Path("one.txt"), Path("two.txt")],
                passphrase="secret",
            )
        )
        async with run_app_test(app, size=(120, 36)) as pilot:
            await pilot.press("3")
            await pilot.click(app.query_one(WorkbenchSteps).button_for("files"))
            await pilot.pause()

            paths = app.query_one("#workflow-add_files-files-body-paths", SelectionList)
            paths.select("file-0")
            await click_when_ready(pilot, "#workspace-add-files-remove-selected")
            await wait_for_condition(
                pilot,
                lambda: app.add_files_state.input_paths == [Path("two.txt")],
                "selected file to be removed",
            )

            assert app.add_files_state.input_paths == [Path("two.txt")]
            assert "one.txt" not in _selection_text(paths)
            assert "two.txt" in _selection_text(paths)

    asyncio.run(run())


def test_rebuild_output_selects_update_task_state_through_typed_events() -> None:
    async def run() -> None:
        app = EthernityApp(
            rebuild_state=RebuildTaskState(
                backup_folder=Path("backup"),
                allow_stale_head=True,
                passphrase="secret",
                output_dir=Path("rebuilt"),
            )
        )
        async with run_app_test(app, size=(120, 36)) as pilot:
            await pilot.press("4")
            await pilot.click(app.query_one(WorkbenchSteps).button_for("output"))
            await pilot.pause()

            paper = app.query_one("#workspace-rebuild-paper", Select)
            design = app.query_one("#workspace-rebuild-design", Select)
            paper.value = "LETTER"
            design.value = "forge"
            await wait_for_condition(
                pilot,
                lambda: (
                    app.rebuild_state.paper_size == "LETTER" and app.rebuild_state.design == "forge"
                ),
                "rebuild paper and design selections to reach task state",
            )

            assert app.rebuild_state.paper_size == "LETTER"
            assert app.rebuild_state.design == "forge"
            assert app.query_one("#rebuild-step-stack", WorkflowStepStack).active_step == "output"
            assert app.workflow_ui_states["rebuild"].is_touched("output")
            assert not app.workflow_ui_states["rebuild"].is_touched("source")

    asyncio.run(run())


@pytest.mark.portability
def test_rebuild_folder_action_opens_directory_picker() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(100, 32)) as pilot:
            await pilot.press("4")
            await click_when_ready(pilot, "#workflow-rebuild-source-body-secondary-0")
            await wait_for_widget(pilot, "#file-picker-cancel")

            assert isinstance(app.screen, FilePickerScreen)
            assert app.screen._mode == FilePickerMode.OPEN_DIRECTORY

    asyncio.run(run())


def _selection_text(selection: SelectionList) -> str:
    return "\n".join(str(option.prompt) for option in selection.options)


def _empty_summary() -> SummaryPresentation:
    return SummaryPresentation(title="", items=(), blockers=(), warnings=())
