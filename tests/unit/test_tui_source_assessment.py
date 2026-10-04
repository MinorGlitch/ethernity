from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from ethernity.app.application import EthernityApp
from ethernity.app.workflow_presenter import build_guided_workflow
from ethernity.app.workflow_state import WorkflowUiState
from ethernity.encoding.framing import Frame, FrameType, encode_frame
from ethernity.encoding.zbase32 import encode_zbase32
from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.models import TaskIssue
from ethernity.tasks.presentation.models import SourceBodyPresentation, SummaryPresentation
from ethernity.tasks.restore import RestoreTaskState
from ethernity.tasks.source_assessment import (
    SourceAssessment,
    assess_source_request,
    recovery_source_request,
    source_freshness_status,
)
from ethernity.workflows.recovery.models import RecoveryUnlockStatus


def _missing_unlock() -> RecoveryUnlockStatus:
    return RecoveryUnlockStatus(
        mode="missing",
        passphrase_provided=False,
        validated_shard_count=0,
        required_shard_threshold=None,
        satisfied=False,
    )


def test_source_freshness_status_preserves_scan_policy() -> None:
    scans = [Path("backup.pdf")]

    assert (
        source_freshness_status([], expected_head_doc_hash=None, allow_stale_head=False) == "ready"
    )
    assert (
        source_freshness_status(scans, expected_head_doc_hash="ab" * 32, allow_stale_head=False)
        == "ready"
    )
    assert (
        source_freshness_status(scans, expected_head_doc_hash=None, allow_stale_head=True)
        == "warning"
    )
    assert (
        source_freshness_status(scans, expected_head_doc_hash=None, allow_stale_head=False)
        == "missing"
    )


def test_recovery_source_assessment_exposes_identity_and_document_count(monkeypatch) -> None:
    request = recovery_source_request(
        issue_section="source",
        scan_paths=[Path("backup.pdf")],
    )
    assert request is not None
    inspection = SimpleNamespace(
        source_frames=(SimpleNamespace(frame_type=FrameType.MAIN_DOCUMENT, doc_id=b"\x12" * 8),),
        main_frames=(),
        auth_frames=(),
        doc_id=b"\x12" * 8,
        doc_hash=b"\x12" * 32,
        decoded_import_session=None,
        unlock=_missing_unlock(),
        blocking_issues=(
            {
                "code": "PASSPHRASE_REQUIRED",
                "message": "unlock later",
            },
        ),
    )
    monkeypatch.setattr(
        "ethernity.tasks.source_assessment.inspect_recovery",
        lambda _request: inspection,
    )

    assessment = assess_source_request(request)

    assert assessment.backup_identity == "12" * 8
    assert assessment.version_summary == "1 backup document found"
    assert assessment.issue is None


def test_mixed_source_assessment_preserves_every_document_carrier(monkeypatch) -> None:
    frame = Frame(
        version=1,
        frame_type=FrameType.MAIN_DOCUMENT,
        doc_id=b"\x12" * 8,
        index=0,
        total=1,
        data=b"payload",
    )
    request = recovery_source_request(
        issue_section="source",
        scan_paths=[Path("renamed.pdf")],
        recovery_text=encode_zbase32(encode_frame(frame)),
        recovery_text_file=Path("transcribed.txt"),
        payloads_file=Path("payloads.txt"),
    )
    calls = []

    def inspect_recovery(recovery_request):
        calls.append(recovery_request)
        return SimpleNamespace(
            source_frames=(frame,),
            main_frames=(),
            auth_frames=(),
            doc_id=frame.doc_id,
            doc_hash=b"\x12" * 32,
            decoded_import_session=None,
            unlock=_missing_unlock(),
            blocking_issues=(),
        )

    monkeypatch.setattr("ethernity.tasks.source_assessment.inspect_recovery", inspect_recovery)
    assert request is not None

    assessment = assess_source_request(request)

    assert request.source_kind == "recovery_inputs"
    assert assessment.source_label == "Backup documents"
    assert assessment.issue is None
    assert len(calls) == 1
    assert calls[0].scan_paths == (Path("renamed.pdf"),)
    assert calls[0].frames == (frame,)
    assert calls[0].recovery_text_file == Path("transcribed.txt")
    assert calls[0].payloads_file == Path("payloads.txt")


def test_add_files_assessment_error_blocks_the_source_section(monkeypatch) -> None:
    inspection = SimpleNamespace(
        source_frames=(SimpleNamespace(frame_type=FrameType.MAIN_DOCUMENT, doc_id=b"\xab" * 8),),
        main_frames=(),
        auth_frames=(),
        doc_id=b"\xab" * 8,
        doc_hash=b"\xab" * 32,
        decoded_import_session=None,
        unlock=_missing_unlock(),
        blocking_issues=(
            {
                "code": "MAIN_DOCUMENTS_INVALID",
                "message": "The supplied documents are incomplete.",
            },
        ),
    )
    monkeypatch.setattr(
        "ethernity.tasks.source_assessment.inspect_recovery",
        lambda _args: inspection,
    )
    state = AddFilesTaskState(
        source_paths=[Path("renamed-root.pdf")],
        output_dir=Path("update-out"),
        allow_stale_head=True,
        input_paths=[Path("new.txt")],
        passphrase="secret",
    )

    assessment = state.assess_source()
    validation = state.validate_task()

    assert assessment is not None
    assert assessment.backup_identity == "ab" * 8
    assert assessment.version_summary == "1 backup document found"
    assert assessment.issue is not None
    assert any(issue.code == "MAIN_DOCUMENTS_INVALID" for issue in validation.issues)

    state.source_paths = [Path("different-scan.png")]
    assert state.current_source_assessment() is None
    assert all(issue.code != "MAIN_DOCUMENTS_INVALID" for issue in state.validate_task().issues)


def test_source_presentation_shows_document_details_errors_and_loading(monkeypatch) -> None:
    state = RestoreTaskState(source_paths=[Path("scan.pdf")])
    monkeypatch.setattr(
        "ethernity.tasks.source_assessment.assess_source_request",
        lambda request: SourceAssessment(
            source_kind=request.source_kind,
            source_label=request.source_label,
            source_summary=request.source_summary,
            backup_identity="cafe1234",
            version_summary="2 backup documents found",
            issue=TaskIssue(
                code="SOURCE_INVALID",
                message="The selected pages do not form one recoverable backup.",
                section="source",
            ),
        ),
    )
    state.assess_source()
    ui_state = WorkflowUiState.start("source", "unlock", "target", "destination")
    ui_state.touch("source")
    validation = state.validate_task()

    workflow = build_guided_workflow(
        task="restore",
        state=state,
        validation=validation,
        ui_state=ui_state,
        review_summary=SummaryPresentation(title="", items=(), blockers=(), warnings=()),
        review_label="Review restore",
    )

    assert workflow is not None
    body = workflow.steps[0].body
    assert isinstance(body, SourceBodyPresentation)
    assert body.assessment is not None
    assert body.assessment.backup_identity == "cafe1234"
    assert body.assessment.version_summary == "2 backup documents found"
    assert body.notice is not None
    assert body.notice.tone == "error"
    assert workflow.steps[0].state == "current"
    assert workflow.steps[0].severity == "error"
    assessment_message = "The selected pages do not form one recoverable backup."
    presented_messages = (
        body.notice.message,
        *(step.issue.message for step in workflow.steps if step.issue is not None),
    )
    assert presented_messages.count(assessment_message) == 1

    ui_state.source_assessment_loading = True
    loading_workflow = build_guided_workflow(
        task="restore",
        state=state,
        validation=validation,
        ui_state=ui_state,
        review_summary=SummaryPresentation(title="", items=(), blockers=(), warnings=()),
        review_label="Review restore",
    )
    assert loading_workflow is not None
    assert isinstance(loading_workflow.steps[0].body, SourceBodyPresentation)
    assert loading_workflow.steps[0].body.loading


def test_source_mutation_runs_assessment_in_background(monkeypatch) -> None:
    def assess(request) -> SourceAssessment:
        return SourceAssessment(
            source_kind=request.source_kind,
            source_label=request.source_label,
            source_summary=request.source_summary,
            backup_identity="deadcafe",
            version_summary="1 backup document found",
        )

    monkeypatch.setattr(
        "ethernity.tasks.source_assessment.assess_source_request",
        assess,
    )

    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.press("2")
            app._apply_restore_sources_picked((Path("scan.pdf"),))
            assert app.workflow_ui_states["restore"].source_assessment_loading

            await pilot.pause()

            assessment = app.restore_state.current_source_assessment()
            assert assessment is not None
            assert assessment.backup_identity == "deadcafe"
            assert not app.workflow_ui_states["restore"].source_assessment_loading

    asyncio.run(run())


def test_programmatic_auth_select_sync_does_not_start_source_assessment() -> None:
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
            ui_state = app.workflow_ui_states["restore"]
            ui_state.activate("destination")
            app.refresh_task_view()
            await pilot.pause()

            assert ui_state.active_step == "destination"
            assert not ui_state.source_assessment_loading

    asyncio.run(run())


def test_destination_remains_editable_while_source_is_loading() -> None:
    state = RestoreTaskState(
        source_paths=[Path("scan.pdf")],
        passphrase="secret",
        output_path=Path("recovered"),
    )
    ui_state = WorkflowUiState.start("source", "unlock", "target", "destination")
    ui_state.activate("destination")
    ui_state.source_assessment_loading = True

    workflow = build_guided_workflow(
        task="restore",
        state=state,
        validation=state.validate_task(),
        ui_state=ui_state,
        review_summary=SummaryPresentation(title="", items=(), blockers=(), warnings=()),
        review_label="Review restore",
    )

    assert workflow is not None
    assert workflow.active_step == "destination"
    assert ui_state.active_step == "destination"
    assert all(step.state != "locked" for step in workflow.steps)
    assert isinstance(workflow.steps[0].body, SourceBodyPresentation)
    assert workflow.steps[0].body.loading
