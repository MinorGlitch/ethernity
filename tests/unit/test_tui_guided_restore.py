from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import RadioSet

from ethernity.app.application import EthernityApp
from ethernity.app.screens.edit_field import EditFieldScreen
from ethernity.app.screens.file_picker import FilePickerScreen
from ethernity.app.widgets.guided_workflow import InlineNotice, WorkflowStepStack
from ethernity.app.workflow_presenter import build_guided_workflow
from ethernity.app.workflow_state import WorkflowUiState
from ethernity.tasks.presentation.models import SummaryPresentation
from ethernity.tasks.restore import RestoreTaskState


def test_restore_workflow_gates_errors_until_the_step_is_attempted() -> None:
    state = RestoreTaskState()
    validation = state.validate_task()
    ui_state = WorkflowUiState.start("source", "unlock", "target", "destination")

    initial = build_guided_workflow(
        task="restore",
        state=state,
        validation=validation,
        ui_state=ui_state,
        review_summary=_empty_summary(),
        review_label="Review restore",
    )

    assert initial is not None
    assert initial.steps[0].state == "current"
    assert initial.steps[0].issue is None
    assert initial.steps[1].state == "locked"
    target = initial.steps[2].body
    assert any(choice.key == "latest" and choice.selected for choice in target.choices)

    ui_state.touch("source")
    attempted = build_guided_workflow(
        task="restore",
        state=state,
        validation=validation,
        ui_state=ui_state,
        review_summary=_empty_summary(),
        review_label="Review restore",
    )

    assert attempted is not None
    assert attempted.steps[0].state == "current"
    assert attempted.steps[0].severity == "error"
    assert attempted.steps[0].issue is not None
    assert attempted.steps[0].issue.message == "Choose backup material."


def test_restore_primary_action_advances_steps_then_opens_review() -> None:
    async def run() -> None:
        app = EthernityApp(
            restore_state=RestoreTaskState(
                source_paths=[Path("scan.pdf")],
                passphrase="secret",
                output_path=Path("recovered"),
            )
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.press("2")
            await pilot.pause()

            stack = app.query_one(WorkflowStepStack)
            assert stack.active_step == "source"

            for expected_step in ("unlock", "target", "destination"):
                await pilot.click("#canvas-primary")
                await pilot.pause()
                assert stack.active_step == expected_step

            await pilot.click("#canvas-primary")
            await pilot.pause()

            assert app.screen.query_one("#review-modal")

    asyncio.run(run())


def test_restore_source_method_routes_to_its_contextual_editor() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(100, 32)) as pilot:
            await pilot.press("2")
            source_methods = app.query_one("#workflow-restore-source-body-methods", RadioSet)
            source_methods.focus()

            await pilot.press("space")
            await pilot.pause()

            assert isinstance(app.screen, FilePickerScreen)
            await pilot.click("#file-picker-cancel")
            await pilot.pause()
            assert app.screen.focused is source_methods

            source_issue = app.query_one("#workflow-restore-source-header").parent.query_one(
                InlineNotice
            )
            assert source_issue.display
            assert "Choose backup material" in str(source_issue.content)

    asyncio.run(run())


def test_restore_specific_version_choice_opens_the_matching_editor() -> None:
    async def run() -> None:
        app = EthernityApp(
            restore_state=RestoreTaskState(
                source_paths=[Path("scan.pdf")],
                passphrase="secret",
            )
        )
        async with app.run_test(size=(100, 32)) as pilot:
            await pilot.press("2")
            await pilot.click("#canvas-primary")
            await pilot.click("#canvas-primary")
            await pilot.pause()

            target = app.query_one("#workflow-restore-target-body-choices", RadioSet)
            target.focus()
            await pilot.press("right", "right", "space")
            await pilot.pause()

            assert isinstance(app.screen, EditFieldScreen)
            assert app.restore_state.target == "specific_update"

    asyncio.run(run())


def _empty_summary() -> SummaryPresentation:
    return SummaryPresentation(title="", items=(), blockers=(), warnings=())
