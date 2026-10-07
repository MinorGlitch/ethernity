from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Input, RadioSet

from ethernity.app.application import EthernityApp
from ethernity.app.screens.edit_field import EditFieldScreen
from ethernity.app.screens.file_picker import FilePickerScreen
from ethernity.app.widgets.workbench import WorkbenchSteps
from ethernity.app.widgets.workflow.controls import InlineNotice
from ethernity.app.widgets.workflow.steps import WorkflowStepStack
from ethernity.app.widgets.workflow.unlock import UnlockEditor
from ethernity.app.workflow_registry import build_guided_workflow
from ethernity.app.workflow_state import WorkflowUiState
from ethernity.tasks.presentation.models import SourceBodyPresentation, SummaryPresentation
from ethernity.tasks.restore import RestoreTaskState
from ethernity.tasks.source_assessment import SourceAssessment


def test_restore_discloses_dependent_sections_and_shows_errors_after_editing() -> None:
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
    assert initial.steps[1].state == "available"
    assert not initial.steps[1].visible
    assert not initial.steps[2].visible
    assert initial.steps[-1].visible
    assert initial.primary_action.label == "Review restore"
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
    assert attempted.steps[0].issue.message == "Choose backup documents."


def test_restore_review_step_opens_review_from_any_editor() -> None:
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

            await pilot.click(app.query_one(WorkbenchSteps).button_for("review"))
            await pilot.pause()

            assert app.screen.query_one("#review-modal")
            assert stack.active_step == "source"

    asyncio.run(run())


def test_restore_document_action_opens_picker_and_returns_focus() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(100, 32)) as pilot:
            await pilot.press("2")
            load_documents = app.query_one("#workflow-restore-source-body-load")
            load_documents.focus()

            await pilot.press("enter")
            await pilot.pause()

            assert isinstance(app.screen, FilePickerScreen)
            await pilot.click("#file-picker-cancel")
            await pilot.pause()
            assert app.screen.focused is load_documents

            source_issue = app.query_one("#workflow-restore-source").query_one(InlineNotice)
            assert not source_issue.display
            await pilot.click("#canvas-primary")
            await pilot.pause()
            assert source_issue.display
            assert "Choose backup documents" in str(source_issue.content)

    asyncio.run(run())


def test_restore_specific_version_choice_opens_the_matching_editor() -> None:
    async def run() -> None:
        state = RestoreTaskState(
            source_paths=[Path("scan.pdf")],
            passphrase="secret",
        )
        app = EthernityApp(restore_state=state)
        state = app.restore_state
        request = state.source_assessment_request()
        assert request is not None
        state.store_source_assessment(
            request,
            SourceAssessment(
                source_kind=request.source_kind,
                source_label=request.source_label,
                source_summary=request.source_summary,
                has_updates=True,
            ),
        )
        async with app.run_test(size=(100, 32)) as pilot:
            await pilot.press("2")
            await pilot.click(app.query_one(WorkbenchSteps).button_for("target"))
            await pilot.pause()

            target = app.query_one("#workflow-restore-target-body-choices", RadioSet)
            target.focus()
            await pilot.press("right", "right", "space")
            await pilot.pause()

            assert isinstance(app.screen, EditFieldScreen)
            assert app.restore_state.target == "specific_update"

    asyncio.run(run())


def test_restore_source_changes_do_not_collapse_destination_editing() -> None:
    state = RestoreTaskState(source_paths=[Path("scan.pdf")], output_path=Path("recovered"))
    ui_state = WorkflowUiState.start("source", "unlock", "target", "destination")
    ui_state.activate("destination")
    state.source_paths = []

    workflow = build_guided_workflow(
        task="restore",
        state=state,
        validation=state.validate_task(),
        ui_state=ui_state,
        review_summary=_empty_summary(),
        review_label="Review restore",
    )

    assert workflow is not None
    assert workflow.active_step == "destination"
    assert workflow.steps[-1].state == "current"
    assert workflow.steps[-1].visible
    assert workflow.steps[0].state == "available"


def test_restore_version_is_hidden_for_inspected_backup_without_updates() -> None:
    state = RestoreTaskState(source_paths=[Path("root.pdf")])
    request = state.source_assessment_request()
    assert request is not None
    state.store_source_assessment(
        request,
        SourceAssessment(
            source_kind=request.source_kind,
            source_label=request.source_label,
            source_summary=request.source_summary,
            has_updates=False,
        ),
    )
    workflow = build_guided_workflow(
        task="restore",
        state=state,
        validation=state.validate_task(),
        ui_state=WorkflowUiState.start("source", "unlock", "target", "destination"),
        review_summary=_empty_summary(),
        review_label="Review restore",
    )

    assert workflow is not None
    assert not workflow.steps[2].visible
    assert state.target == "latest"
    assert workflow.steps[1].visible


def test_restore_inline_path_and_passphrase_edits_update_state_without_modals() -> None:
    async def run() -> None:
        app = EthernityApp(
            restore_state=RestoreTaskState(
                source_paths=[Path("root.pdf")],
                recovery_documents=[Path("sheet.pdf")],
            )
        )
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("2")
            await pilot.click(app.query_one(WorkbenchSteps).button_for("destination"))
            destination = app.query_one("#workflow-restore-destination-body-value", Input)
            destination.focus()
            await pilot.press(*"~/Recovered", "enter")
            await pilot.pause()
            assert app.restore_state.output_path == Path("~/Recovered").expanduser()
            assert app.restore_state.source_paths == [Path("root.pdf")]

            await pilot.click(app.query_one(WorkbenchSteps).button_for("unlock"))
            unlock = app.query_one("#workflow-restore-unlock-body", UnlockEditor)
            methods = unlock.query_one(RadioSet)
            methods.focus()
            await pilot.press("space")
            await pilot.pause()
            passphrase = unlock.query_one(Input)
            assert app.screen is app.screen_stack[0]
            assert passphrase.password
            assert app.screen.focused is passphrase
            await pilot.press(*"backup-secret", "enter")
            await pilot.pause()
            assert app.restore_state.passphrase == "backup-secret"
            assert app.restore_state.recovery_documents == []
            assert passphrase.value == ""

    asyncio.run(run())


def test_restore_explicit_version_remains_editable_when_source_changes() -> None:
    state = RestoreTaskState(source_paths=[Path("root.pdf")], target="specific_update")
    ui_state = WorkflowUiState.start("source", "unlock", "target", "destination")
    ui_state.activate("target")
    ui_state.mark_review_attempted()
    workflow = build_guided_workflow(
        task="restore",
        state=state,
        validation=state.validate_task(),
        ui_state=ui_state,
        review_summary=_empty_summary(),
        review_label="Review restore",
    )

    assert workflow is not None
    assert workflow.steps[2].visible
    assert workflow.steps[2].severity == "error"
    assert workflow.active_step == "target"


def test_restore_source_assessment_does_not_ask_for_already_supplied_passphrase() -> None:
    state = RestoreTaskState(source_paths=[Path("root.pdf")], passphrase="secret")
    request = state.source_assessment_request()
    assert request is not None
    state.store_source_assessment(
        request,
        SourceAssessment(
            source_kind=request.source_kind,
            source_label=request.source_label,
            source_summary=request.source_summary,
            unlock_summary="Passphrase required",
        ),
    )
    workflow = build_guided_workflow(
        task="restore",
        state=state,
        validation=state.validate_task(),
        ui_state=WorkflowUiState.start("source", "unlock", "target", "destination"),
        review_summary=_empty_summary(),
        review_label="Review restore",
    )
    assert workflow is not None
    assert isinstance(workflow.steps[0].body, SourceBodyPresentation)
    assessment = workflow.steps[0].body.assessment
    assert assessment is not None
    assert assessment.unlock_summary == ""


def _empty_summary() -> SummaryPresentation:
    return SummaryPresentation(title="", items=(), blockers=(), warnings=())
