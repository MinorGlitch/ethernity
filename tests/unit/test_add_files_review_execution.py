from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from click.testing import CliRunner

from ethernity.app.application import EthernityApp
from ethernity.app.execution import ReviewedTask
from ethernity.config.paths import DEFAULT_CONFIG_PATH
from ethernity.encoding.framing import Frame, FrameType
from ethernity.formats.extension_mode import UpdateMode
from ethernity.run.cli import cli
from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.models import TaskExecutionResult, TaskResultDetail
from ethernity.workflows.add_files.errors import AddFilesIssue
from ethernity.workflows.add_files.execution import AssessedAddFilesRun
from ethernity.workflows.add_files.request import AddFilesRequest
from ethernity.workflows.add_files.service import (
    AddFilesAssessment,
    AddFilesExecutionResult,
    assess_add_files,
    execute_add_files,
)
from ethernity.workflows.shared import issue_codes
from ethernity.workflows.shared.requests import ReplacementRecoveryRequest
from tests.support.app import run_app_test


def _valid_config(tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_bytes(DEFAULT_CONFIG_PATH.read_bytes())
    return path


def _fake_assessed(marker: bytes = b"A") -> AssessedAddFilesRun:
    stats = SimpleNamespace(
        changed_file_count=2,
        file_bytes=12,
        new_chunks=1,
        reused_chunks=2,
    )
    prepared = SimpleNamespace(
        plan=SimpleNamespace(update_mode=UpdateMode.INCREMENTAL),
        request=SimpleNamespace(base_directory=None),
        next_index=3,
        changed_paths=("changed.txt",),
        new_paths=("new.txt",),
        unchanged_paths=("same.txt",),
        parent_doc_hash=b"P" * 32,
        encryption_passphrase="resolved-passphrase",
        source_frames=(
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"S" * 8,
                index=0,
                total=1,
                data=b"source",
            ),
        ),
    )
    encrypted = SimpleNamespace(
        built=SimpleNamespace(stats=stats),
        plaintext=b"plaintext-" + marker,
        ciphertext=b"ciphertext-" + marker,
        doc_id=b"D" * 8,
        doc_hash=marker * 32,
    )
    output_settings = SimpleNamespace(
        config=SimpleNamespace(paper_size="A4", design_name="sentinel"),
        qr_chunk_size=512,
    )
    return AssessedAddFilesRun(
        prepared=prepared, encrypted=encrypted, output_settings=output_settings
    )


def _fake_executed(assessed: AssessedAddFilesRun, output_root: Path) -> SimpleNamespace:
    result = SimpleNamespace(
        index=assessed.prepared.next_index,
        doc_id=assessed.encrypted.doc_id,
        doc_hash=assessed.encrypted.doc_hash,
        qr_document_path=output_root / "qr.pdf",
        recovery_document_path=output_root / "recovery.pdf",
        parent_head_index=2,
        final_dir=output_root,
        recovery_frames=(
            Frame(
                version=1,
                frame_type=FrameType.AUTH,
                doc_id=b"D" * 8,
                index=0,
                total=1,
                data=b"update-auth",
            ),
        ),
    )
    return SimpleNamespace(
        prepared=assessed.prepared,
        output_settings=assessed.output_settings,
        publish=SimpleNamespace(encrypted=assessed.encrypted),
        result=result,
    )


@pytest.mark.parametrize(
    ("has_issues", "has_payload"),
    [(True, False), (True, True), (False, False)],
)
def test_unready_assessment_never_publishes(
    monkeypatch: pytest.MonkeyPatch, has_issues: bool, has_payload: bool
) -> None:
    issues = (AddFilesIssue(code="SOURCE_INVALID", message="Invalid source"),) if has_issues else ()
    assessment = AddFilesAssessment(
        request=AddFilesRequest(),
        assessed=_fake_assessed() if has_payload else None,
        issues=issues,
    )
    publish = mock.Mock()
    monkeypatch.setattr("ethernity.workflows.add_files.service.execute_assessed_add_files", publish)

    result = execute_add_files(assessment)

    publish.assert_not_called()
    assert not result.ok
    assert result.executed is None
    if has_issues:
        assert result.issues == issues
        assert result.execution_issues == ()
    else:
        assert result.issues[0].code == issue_codes.RUNTIME_ERROR
        assert "must pass assessment" in result.issues[0].message


def test_task_uses_saved_add_files_defaults_without_hardcoded_overrides(
    tmp_path: Path,
) -> None:
    config_path = _valid_config(tmp_path)
    config_text = config_path.read_text(encoding="utf-8")
    add_files_start = config_text.index("[defaults.add_files]")
    recover_start = config_text.index("[defaults.recover]")
    add_files = config_text[add_files_start:recover_start]
    add_files = add_files.replace('base_dir = ""', f"base_dir = {json.dumps(str(tmp_path))}", 1)
    config_path.write_text(
        config_text[:add_files_start] + add_files + config_text[recover_start:],
        encoding="utf-8",
    )

    state = AddFilesTaskState(
        config_path=config_path,
        source_paths=[Path("published")],
        output_dir=Path("published"),
        allow_stale_head=True,
        input_paths=[Path("new.txt")],
        passphrase="secret",
    )
    request = state.to_add_files_request()

    assert request.base_directory == str(tmp_path)
    assert request.paper_size is None
    assert request.design is None


def test_add_files_has_no_extension_specific_recovery_or_signing_policy() -> None:
    removed_fields = {
        "unlock_policy",
        "recovery_document_count",
        "recovery_document_threshold",
        "signing_key_mode",
        "signing_key_recovery_count",
        "signing_key_recovery_threshold",
    }

    assert removed_fields.isdisjoint(AddFilesTaskState.model_fields)


def test_optional_recovery_sheets_delegate_to_replacement_recovery(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = _valid_config(tmp_path)
    assessed = _fake_assessed()
    published = tmp_path / "published"
    replacement_requests: list[ReplacementRecoveryRequest] = []
    output_dir = (
        tmp_path
        / "published-recovery-sheets"
        / (f"replacement-recovery-{assessed.encrypted.doc_id.hex()}")
    )
    request = AddFilesRequest(
        config_path=str(config_path),
        output_dir=str(published),
        input_paths=(str(tmp_path / "new.txt"),),
        create_recovery_sheets=True,
        recovery_threshold=2,
        recovery_sheet_count=3,
    )
    assessment = AddFilesAssessment(
        request=request,
        assessed=assessed,
        recovery_sheet_output_dir=output_dir,
    )
    monkeypatch.setattr(
        "ethernity.workflows.add_files.service.execute_assessed_add_files",
        lambda *_args, **_kwargs: _fake_executed(assessed, published),
    )

    def create_recovery_sheets(request):
        replacement_requests.append(request)
        output_dir = request.output_dir
        assert output_dir is not None
        return SimpleNamespace(
            shard_paths=tuple(output_dir / f"shard-{index}.pdf" for index in range(1, 4)),
            signing_key_shard_paths=(),
        )

    monkeypatch.setattr(
        "ethernity.workflows.add_files.service.execute_replacement_recovery",
        create_recovery_sheets,
    )
    execution = execute_add_files(assessment)
    monkeypatch.setattr("ethernity.tasks.add_files.assess_add_files", lambda _request: assessment)
    monkeypatch.setattr(
        "ethernity.tasks.add_files.execute_add_files",
        lambda _assessment, **_kwargs: execution,
    )
    state = AddFilesTaskState(
        config_path=config_path,
        source_paths=[published],
        output_dir=published,
        allow_stale_head=True,
        input_paths=[tmp_path / "new.txt"],
        recovery_documents=[tmp_path / "root-sheet.pdf"],
        create_recovery_sheets=True,
        recovery_threshold=2,
        recovery_sheet_count=3,
    )
    state.prepare_review(force=True)
    plan = state.execution_plan()

    result = state.execute()

    assert result.ok
    assert len(replacement_requests) == 1
    recovery_request = replacement_requests[0]
    assert recovery_request.scan_paths == ()
    assert recovery_request.frames == (
        *assessed.prepared.source_frames,
        *_fake_executed(assessed, published).result.recovery_frames,
    )
    assert recovery_request.passphrase == "resolved-passphrase"
    assert recovery_request.extension_doc_hash == assessed.encrypted.doc_hash.hex()
    assert recovery_request.expected_head_doc_hash == assessed.encrypted.doc_hash.hex()
    assert recovery_request.shard_threshold == 2
    assert recovery_request.shard_count == 3
    assert recovery_request.create_passphrase_shards
    assert not recovery_request.create_signing_key_shards
    assert recovery_request.output_dir == output_dir
    assert plan.output_paths == (
        published,
        output_dir,
    )
    assert execution.recovery_sheets.status == "created"
    assert len(result.output_paths) == 5
    assert result.recovery_check_paths == (
        published / "qr.pdf",
        *execution.recovery_sheets.paths,
    )
    assert "3 created; 2 needed" in str(
        next(detail for detail in result.details if detail.key == "recovery_sheets").value
    )


def test_recovery_sheet_failure_reports_the_published_update_without_inviting_retry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = _valid_config(tmp_path)
    assessed = _fake_assessed()
    published = tmp_path / "published"
    output_dir = tmp_path / "published-recovery-sheets" / "replacement-recovery"
    request = AddFilesRequest(
        config_path=str(config_path),
        output_dir=str(published),
        input_paths=(str(tmp_path / "new.txt"),),
        create_recovery_sheets=True,
    )
    assessment = AddFilesAssessment(
        request=request,
        assessed=assessed,
        recovery_sheet_output_dir=output_dir,
    )
    monkeypatch.setattr(
        "ethernity.workflows.add_files.service.execute_assessed_add_files",
        lambda *_args, **_kwargs: _fake_executed(assessed, published),
    )

    def fail_recovery_sheets(_request):
        raise ValueError("printer backend failed")

    monkeypatch.setattr(
        "ethernity.workflows.add_files.service.execute_replacement_recovery",
        fail_recovery_sheets,
    )
    execution = execute_add_files(assessment)
    monkeypatch.setattr("ethernity.tasks.add_files.assess_add_files", lambda _request: assessment)
    monkeypatch.setattr(
        "ethernity.tasks.add_files.execute_add_files",
        lambda _assessment, **_kwargs: execution,
    )
    state = AddFilesTaskState(
        config_path=config_path,
        source_paths=[published],
        output_dir=published,
        allow_stale_head=True,
        input_paths=[tmp_path / "new.txt"],
        passphrase="secret",
        create_recovery_sheets=True,
    )
    state.prepare_review(force=True)

    result = state.execute()

    assert result.ok
    assert result.status == "partially_succeeded"
    assert execution.partial
    assert "but recovery sheets were not created" in result.message
    assert len(result.output_paths) == 2
    assert result.recovery_check_paths == (published / "qr.pdf",)
    assert (
        "Not created: printer backend failed"
        == next(detail for detail in result.details if detail.key == "recovery_sheets").value
    )
    assert "Do not run Add Files again" in result.next_steps[0]


def test_existing_recovery_sheet_output_blocks_publication(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = _valid_config(tmp_path)
    assessed = _fake_assessed()
    published = tmp_path / "published"
    output_dir = (
        tmp_path
        / "published-recovery-sheets"
        / (f"replacement-recovery-{assessed.encrypted.doc_id.hex()}")
    )
    output_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "ethernity.workflows.add_files.service.prepare_add_files_run",
        lambda _request: object(),
    )
    monkeypatch.setattr(
        "ethernity.workflows.add_files.service.assess_prepared_add_files",
        lambda _prepared: assessed,
    )
    state = AddFilesTaskState(
        config_path=config_path,
        source_paths=[published],
        output_dir=published,
        allow_stale_head=True,
        input_paths=[tmp_path / "new.txt"],
        passphrase="secret",
        create_recovery_sheets=True,
    )
    assessment = assess_add_files(state.to_add_files_request())
    monkeypatch.setattr("ethernity.tasks.add_files.assess_add_files", lambda _request: assessment)
    state.prepare_review(force=True)

    validation = state.validate_task()

    assert not validation.ready
    assert validation.issues[0].code == "ADD_FILES_RECOVERY_OUTPUT_EXISTS"
    assert validation.issues[0].section == "advanced"


def test_review_assessment_is_shared_and_exact_payload_is_executed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = _valid_config(tmp_path)
    assessed = _fake_assessed()
    assessment_calls: list[object] = []
    execution_calls: list[object] = []

    def fake_assess(request):
        assessment_calls.append(request)
        return AddFilesAssessment(request=request, assessed=assessed)

    def fake_execute(assessment, **_kwargs):
        execution_calls.append(assessment.assessed)
        return AddFilesExecutionResult(
            assessment=assessment,
            executed=_fake_executed(assessment.assessed, tmp_path / "published"),
        )

    monkeypatch.setattr("ethernity.tasks.add_files.assess_add_files", fake_assess)
    monkeypatch.setattr("ethernity.tasks.add_files.execute_add_files", fake_execute)

    state = AddFilesTaskState(
        config_path=config_path,
        source_paths=[tmp_path / "published"],
        output_dir=tmp_path / "published",
        allow_stale_head=True,
        input_paths=[tmp_path / "new.txt"],
        passphrase="secret",
    )
    state.prepare_review(force=True)

    assert state.validate_task().ready
    assert "03" in state.execution_plan().summary
    preview = state.preview()
    assert any(item.label == "New fingerprint" for item in preview.items)
    assert next(item.detail for item in preview.items if item.label == "Recovery chain") == (
        "Recovery requires the original backup and updates 01 through 03. "
        "Rebuild after publication to create a new standalone backup."
    )
    assert "updates 01 through 03" in state.execution_plan().recovery_notes[1]
    result = state.execute()

    assert len(assessment_calls) == 1
    assert execution_calls == [assessed]
    assert len(result.output_paths) == 2
    assert result.recovery_check_paths == (tmp_path / "published" / "qr.pdf",)
    assert "original backup and updates 01 through 03" in result.next_steps[0]
    assert "Use Rebuild when you want a new standalone backup" in result.next_steps[1]
    assert (
        next(detail for detail in result.details if detail.key == "doc_hash").value
        == (b"A" * 32).hex()
    )


def test_failed_assessment_blocks_review_without_replanning(monkeypatch) -> None:
    calls = 0

    def reject(request):
        nonlocal calls
        calls += 1
        return AddFilesAssessment(
            request=request,
            issues=(
                AddFilesIssue(
                    code=issue_codes.ADD_FILES_NO_CHANGES,
                    message="nothing to publish",
                ),
            ),
        )

    monkeypatch.setattr("ethernity.tasks.add_files.assess_add_files", reject)
    state = AddFilesTaskState(
        source_paths=[Path("published")],
        output_dir=Path("published"),
        allow_stale_head=True,
        input_paths=[Path("same.txt")],
        passphrase="secret",
    )

    state.prepare_review(force=True)
    validation = state.validate_task()
    state.preview()
    state.execution_plan()

    assert not validation.ready
    assert validation.issues[0].code == issue_codes.ADD_FILES_NO_CHANGES
    assert validation.issues[0].section == "files"
    assert calls == 1


@pytest.mark.parametrize(
    ("message", "details", "expected_section"),
    (
        ("Missing ancestor document.", {}, "source"),
        ("Conflicting authenticated histories.", {"extension_index": 2}, "source"),
        ("Invalid document signature.", {"doc_id": "11" * 8}, "source"),
        (
            "Expected head does not match.",
            {"expected_head_doc_hash": "ab" * 32, "validated_head_doc_hash": "cd" * 32},
            "freshness",
        ),
        (
            "Newest loaded version must be acknowledged.",
            {"freshness_scope": "supplied_carriers_only"},
            "freshness",
        ),
    ),
    ids=("missing-ancestor", "fork", "invalid-auth", "pin-mismatch", "freshness-unknown"),
)
def test_add_files_review_routes_invalid_documents_and_head_trust_separately(
    message: str,
    details: dict[str, object],
    expected_section: str,
    monkeypatch,
) -> None:
    issue = AddFilesIssue(
        code=issue_codes.RECOVERY_HEAD_UNTRUSTED,
        message=message,
        details=details,
    )
    monkeypatch.setattr(
        "ethernity.tasks.add_files.assess_add_files",
        lambda request: AddFilesAssessment(request=request, issues=(issue,)),
    )
    state = AddFilesTaskState(
        source_paths=[Path("documents")],
        input_paths=[Path("new.txt")],
        output_dir=Path("update"),
        passphrase="secret",
        expected_head_doc_hash="ab" * 32,
    )

    state.prepare_review(force=True)
    validation = state.validate_task()

    assert not validation.ready
    assert validation.issues[0].section == expected_section
    assert validation.issues[0].message == message
    blocked_sections = [
        section.key for section in validation.sections if section.status == "blocked"
    ]
    assert blocked_sections == [expected_section]


def test_reviewed_task_reuses_assessment_and_ignores_later_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = _valid_config(tmp_path)
    assessed = _fake_assessed(b"R")
    assessment_count = 0
    executed_hashes: list[bytes] = []
    executed_assessments: list[AssessedAddFilesRun] = []
    execution_config_payloads: list[bytes] = []
    reviewed_config_payload = config_path.read_bytes()

    def fake_assess(request):
        nonlocal assessment_count
        assessment_count += 1
        return AddFilesAssessment(request=request, assessed=assessed)

    monkeypatch.setattr("ethernity.tasks.add_files.assess_add_files", fake_assess)

    def fake_execute(assessment, *, config_path=None, **_kwargs):
        value = assessment.assessed
        executed_assessments.append(value)
        executed_hashes.append(value.encrypted.doc_hash)
        assert config_path is not None
        execution_config_payloads.append(Path(config_path).read_bytes())
        return AddFilesExecutionResult(
            assessment=assessment,
            executed=_fake_executed(value, tmp_path / "published"),
        )

    monkeypatch.setattr("ethernity.tasks.add_files.execute_add_files", fake_execute)

    state = AddFilesTaskState(
        config_path=config_path,
        source_paths=[tmp_path / "published"],
        output_dir=tmp_path / "published",
        allow_stale_head=True,
        input_paths=[tmp_path / "reviewed.txt"],
        passphrase="secret",
    )
    state.prepare_review(force=True)
    reviewed_task = ReviewedTask.capture("add_files", state)

    state.input_paths = [tmp_path / "later.txt"]
    config_path.write_text(
        config_path.read_text(encoding="utf-8") + "\n# changed after review\n",
        encoding="utf-8",
    )
    result = reviewed_task.execute()

    assert result.ok
    assert assessment_count == 1
    assert executed_assessments[0] is assessed
    assert executed_hashes == [b"R" * 32]
    assert execution_config_payloads == [reviewed_config_payload]
    assert reviewed_task.state_snapshot.input_paths == [tmp_path / "reviewed.txt"]


@pytest.mark.parametrize("cached_picker", [False, True])
def test_automatic_destination_is_shared_by_preview_plan_and_picker(
    tmp_path: Path, monkeypatch, cached_picker: bool
) -> None:
    destination = tmp_path / "backup-2222222222222222-update-03"
    assessed = _fake_assessed()

    def fake_assess(request):
        return AddFilesAssessment(
            request=replace(request, output_dir=str(destination)), assessed=assessed
        )

    monkeypatch.setattr("ethernity.tasks.add_files.assess_add_files", fake_assess)
    state = AddFilesTaskState(
        config_path=_valid_config(tmp_path),
        source_paths=[tmp_path / "renamed-original.pdf"],
        input_paths=[tmp_path / "new.txt"],
        passphrase="secret",
        allow_stale_head=True,
    )
    state.prepare_review()

    assert state.output_dir is None
    assert state.resolved_output_dir() == destination
    assert state.execution_plan().output_paths == (destination,)
    assert next(item.detail for item in state.preview().items if item.label == "Update folder") == (
        str(destination)
    )
    assert next(section for section in state.sections() if section.key == "output").status == (
        "ready"
    )
    if not cached_picker:
        state.source_paths = [tmp_path / "different-backup.pdf"]
        assert state.resolved_output_dir() is None

    async def run() -> None:
        app = EthernityApp(add_files_state=state)
        async with run_app_test(app, size=(100, 30)) as pilot:
            await pilot.press("3")
            picked = []

            async def capture_picker(**kwargs):
                picked.append(kwargs)

            monkeypatch.setattr(app, "_pick_paths", capture_picker)
            await app.action_edit_output()
            assert picked[0]["selected_paths"] == (destination.parent,)
            assert picked[0]["save_name"] == destination.name

    asyncio.run(run())

    state.source_paths = [tmp_path / "different-backup.pdf"]
    assert state.resolved_output_dir() is None
    state.output_dir = tmp_path / "custom"
    assert state.resolved_output_dir() == tmp_path / "custom"


def test_run_task_and_textual_review_prime_add_files_assessment(monkeypatch) -> None:
    run_calls: list[bool] = []

    def record_run_review(_self, *, force=False):
        run_calls.append(force)

    monkeypatch.setattr(AddFilesTaskState, "prepare_review", record_run_review)
    result = CliRunner().invoke(
        cli,
        [
            "add-files",
            "--scan",
            "published",
            "--output-dir",
            "update",
            "--allow-stale-head",
            "--input",
            "new.txt",
            "--passphrase",
            "secret",
            "--preview",
        ],
    )
    assert result.exit_code == 0
    assert run_calls == [True]

    tui_calls: list[bool] = []

    def record_tui_review(_self, *, force=False):
        tui_calls.append(force)

    monkeypatch.setattr(AddFilesTaskState, "prepare_review", record_tui_review)

    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(100, 30)) as pilot:
            await pilot.press("3")
            await app.action_review()
            await pilot.pause()

    asyncio.run(run())
    assert tui_calls == [True]


def test_run_add_files_blocks_execution_when_assessment_fails(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        cli,
        [
            "add-files",
            "--scan",
            str(tmp_path / "missing-backup"),
            "--output-dir",
            "update",
            "--allow-stale-head",
            "--input",
            str(tmp_path / "missing-input"),
            "--passphrase",
            "secret",
            "--yes",
        ],
    )

    assert result.exit_code == 1
    assert "Add Files is not ready" in result.output
    assert not (tmp_path / "update").exists()


def test_add_files_result_metadata_reaches_text_output(monkeypatch) -> None:
    result = TaskExecutionResult(
        status="succeeded",
        message="Added files as backup update 03.",
        output_paths=(Path("update/qr.pdf"),),
        details=(
            TaskResultDetail(
                key="doc_hash",
                label="New full fingerprint",
                value="ab" * 32,
            ),
            TaskResultDetail(key="new_chunks", label="New chunks", value=4),
        ),
        next_steps=("Keep the original backup and every earlier update.",),
    )
    monkeypatch.setattr(
        AddFilesTaskState,
        "prepare_review",
        lambda _self, *, force=False: None,
    )
    monkeypatch.setattr(AddFilesTaskState, "execute", lambda _self: result)
    command_args = [
        "add-files",
        "--scan",
        "published",
        "--output-dir",
        "update",
        "--allow-stale-head",
        "--input",
        "new.txt",
        "--passphrase",
        "secret",
        "--yes",
    ]

    text_result = CliRunner().invoke(cli, command_args)

    assert text_result.exit_code == 0
    assert "New full fingerprint" in text_result.output
    assert "Keep the original backup and every earlier update." in text_result.output
    assert "New chunks" in text_result.output
    assert str(Path("update/qr.pdf")) in text_result.output
