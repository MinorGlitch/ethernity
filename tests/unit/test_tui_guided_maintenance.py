from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Select, SelectionList

from ethernity.app.application import EthernityApp
from ethernity.app.screens.file_picker import FilePickerMode, FilePickerScreen
from ethernity.app.widgets.guided_workflow import WorkflowStepStack
from ethernity.app.workflow_presenter import build_guided_workflow
from ethernity.app.workflow_state import WorkflowUiState
from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.presentation.models import (
    CompositeBodyPresentation,
    OptionsBodyPresentation,
    SummaryPresentation,
)
from ethernity.tasks.rebuild import RebuildTaskState


def test_add_files_folder_source_makes_output_implicit() -> None:
    state = AddFilesTaskState(
        backup_folder=Path("backup"),
        input_paths=[Path("notes.txt")],
        passphrase="secret",
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
    output = workflow.steps[-1].body
    assert output.display_path == "backup"
    assert output.action is not None
    assert not output.action.visible


def test_rebuild_output_uses_typed_native_layout_selects() -> None:
    state = RebuildTaskState(
        backup_folder=Path("backup"),
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
                backup_folder=Path("backup"),
                input_paths=[Path("one.txt"), Path("two.txt")],
                passphrase="secret",
            )
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.press("3")
            await pilot.click("#canvas-primary")
            await pilot.pause()

            paths = app.query_one("#workflow-add_files-files-body-paths", SelectionList)
            paths.select("file-0")
            await pilot.pause()
            await pilot.click("#workspace-add-files-remove-selected")
            await pilot.pause()

            assert app.add_files_state.input_paths == [Path("two.txt")]
            assert "one.txt" not in _selection_text(paths)
            assert "two.txt" in _selection_text(paths)

    asyncio.run(run())


def test_rebuild_output_selects_update_task_state_through_typed_events() -> None:
    async def run() -> None:
        app = EthernityApp(
            rebuild_state=RebuildTaskState(
                backup_folder=Path("backup"),
                passphrase="secret",
                output_dir=Path("rebuilt"),
            )
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.press("4")
            await pilot.click("#canvas-primary")
            await pilot.pause()
            await pilot.click("#canvas-primary")
            await pilot.pause()

            paper = app.query_one("#workspace-rebuild-paper", Select)
            design = app.query_one("#workspace-rebuild-design", Select)
            paper.value = "LETTER"
            design.value = "forge"
            await pilot.pause()

            assert app.rebuild_state.paper_size == "LETTER"
            assert app.rebuild_state.design == "forge"
            assert app.query_one("#rebuild-step-stack", WorkflowStepStack).active_step == "output"

    asyncio.run(run())


def test_rebuild_source_methods_open_constrained_editors() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(100, 32)) as pilot:
            await pilot.press("4")
            methods = app.query_one("#workflow-rebuild-source-body-methods")
            methods.focus()
            await pilot.press("space")
            await pilot.pause()

            assert isinstance(app.screen, FilePickerScreen)
            assert app.screen._mode == FilePickerMode.OPEN_DIRECTORY

    asyncio.run(run())


def _selection_text(selection: SelectionList) -> str:
    return "\n".join(str(option.prompt) for option in selection.options)


def _empty_summary() -> SummaryPresentation:
    return SummaryPresentation(title="", items=(), blockers=(), warnings=())
