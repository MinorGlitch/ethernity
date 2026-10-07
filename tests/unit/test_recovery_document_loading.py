"""Collections route decoded recovery sheets through existing binding checks."""

from dataclasses import replace
from pathlib import Path

import pytest

from ethernity.encoding.framing import Frame
from ethernity.tasks.recovery_inputs import has_unlock_inputs
from ethernity.tasks.restore import RestoreTaskState
from ethernity.workflows.execution import inspect_recovery
from ethernity.workflows.recovery.frame_inputs import frames_from_payloads
from ethernity.workflows.recovery.planning import plan_from_request
from ethernity.workflows.shared.requests import RecoveryRequest

_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures/v1_2/extension_golden/raw/large_raw_two_extension_chain"
)


@pytest.fixture
def document_frames() -> tuple[list[Frame], list[Frame]]:
    backup = frames_from_payloads(str(_FIXTURE / "root_payloads.txt"))
    sheets = frames_from_payloads(str(_FIXTURE / "root_shard_payloads_threshold.txt"))
    return backup, sheets


def test_collection_detects_authenticated_sheets_and_unlocks_without_separate_input(
    monkeypatch,
    document_frames,
) -> None:
    backup, sheets = document_frames
    monkeypatch.setattr(
        "ethernity.workflows.recovery.inputs.frame_inputs.frames_from_scan",
        lambda paths: [*backup, *sheets],
    )
    state = RestoreTaskState(source_paths=[Path("renamed-folder")])
    assessment = state.assess_source()

    assert assessment is not None
    assert assessment.issue is None
    assert assessment.document_count == 1
    assert not assessment.has_updates
    assert assessment.unlock_ready
    assert assessment.unlock_summary == "Recovery sheets ready: 2 validated."
    assert has_unlock_inputs(state)
    assert not state.recovery_documents
    assert "authentication found for 1" in assessment.document_summary

    plan = plan_from_request(RecoveryRequest(scan_paths=["renamed-folder"], quiet=True))
    assert plan.shard_frames == tuple(sheets)
    assert plan.passphrase
    assert plan.auth_status == "verified"
    assert plan.doc_hash.hex() == assessment.root_doc_hash
    assert plan.expected_head_doc_hash is None

    state.source_paths = [Path("different-folder")]
    assert not has_unlock_inputs(state)


def test_collection_reports_only_missing_recovery_sheets(monkeypatch, document_frames) -> None:
    backup, sheets = document_frames
    monkeypatch.setattr(
        "ethernity.workflows.recovery.inputs.frame_inputs.frames_from_scan",
        lambda paths: [*backup, sheets[0]],
    )
    state = RestoreTaskState(source_paths=[Path("one-sheet-and-backup")])
    assessment = state.assess_source()

    assert assessment is not None
    assert assessment.issue is None
    assert not assessment.unlock_ready
    assert assessment.unlock_summary == "Recovery sheets: 1 of 2 required. Load 1 more sheet."
    assert not has_unlock_inputs(state)


def test_detected_sheet_cannot_establish_unlock_with_wrong_document_binding(
    monkeypatch,
    document_frames,
) -> None:
    backup, sheets = document_frames
    wrong_binding = replace(sheets[0], doc_id=b"wrong-id")
    monkeypatch.setattr(
        "ethernity.workflows.recovery.inputs.frame_inputs.frames_from_scan",
        lambda paths: [*backup, wrong_binding, sheets[1]],
    )
    state = RestoreTaskState(source_paths=[Path("looks-like-a-backup")])
    assessment = state.assess_source()

    assert assessment is not None
    assert not assessment.unlock_ready
    assert assessment.issue is None
    assert assessment.unlock_summary == "The loaded recovery sheets cannot unlock this backup."
    assert not has_unlock_inputs(state)
    assert any(issue.section == "unlock" for issue in state.validate_task().issues)
    inspection = inspect_recovery(RecoveryRequest(scan_paths=tuple(state.source_paths)))
    assert any(issue["code"] == "PASSPHRASE_SHARDS_INVALID" for issue in inspection.blocking_issues)

    state.passphrase = "chosen-passphrase"
    assert has_unlock_inputs(state)
    assert not any(issue.section == "source" for issue in state.validate_task().issues)


def test_explicit_passphrase_takes_precedence_over_detected_sheets(
    monkeypatch,
    document_frames,
) -> None:
    backup, sheets = document_frames
    monkeypatch.setattr(
        "ethernity.workflows.recovery.inputs.frame_inputs.frames_from_scan",
        lambda paths: [*backup, *sheets],
    )
    inspection = inspect_recovery(
        RecoveryRequest(scan_paths=(Path("documents"),), passphrase="chosen-passphrase")
    )
    assert inspection.unlock.mode == "passphrase"
    assert inspection.unlock.resolved_passphrase == "chosen-passphrase"
    assert not inspection.shard_frames


def test_signing_key_sheets_are_distinguished_from_passphrase_sheets(monkeypatch) -> None:
    fixture = (
        Path(__file__).resolve().parents[1] / "fixtures/v1_1/golden/base64/sharded_signing_sharded"
    )
    backup = frames_from_payloads(str(fixture / "main_payloads.txt"))
    passphrase_sheets = frames_from_payloads(str(fixture / "shard_payloads_threshold.txt"))
    signing_sheets = frames_from_payloads(str(fixture / "signing_key_shard_payloads_threshold.txt"))
    monkeypatch.setattr(
        "ethernity.workflows.recovery.inputs.frame_inputs.frames_from_scan",
        lambda paths: [*backup, *passphrase_sheets, *signing_sheets],
    )

    inspection = inspect_recovery(RecoveryRequest(scan_paths=(Path("all-documents"),)))

    assert inspection.unlock.satisfied
    assert inspection.shard_frames == tuple(passphrase_sheets)
    assert inspection.auth_status == "verified"


def test_exported_collection_also_routes_detected_sheets(tmp_path) -> None:
    payloads = tmp_path / "exported.txt"
    payloads.write_text(
        (_FIXTURE / "root_payloads.txt").read_text()
        + "\n"
        + (_FIXTURE / "root_shard_payloads_threshold.txt").read_text(),
        encoding="utf-8",
    )
    state = RestoreTaskState(payloads_file=payloads)

    assessment = state.assess_source()

    assert assessment is not None
    assert assessment.issue is None
    assert assessment.unlock_ready
    assert has_unlock_inputs(state)


def test_explicit_conflicting_unlock_inputs_still_require_one_method(
    monkeypatch,
    document_frames,
) -> None:
    backup, sheets = document_frames
    monkeypatch.setattr(
        "ethernity.workflows.recovery.inputs.frame_inputs.frames_from_scan",
        lambda paths: backup,
    )
    with pytest.raises(ValueError, match="either shard inputs or passphrase"):
        inspect_recovery(
            RecoveryRequest(
                scan_paths=(Path("documents"),),
                passphrase="chosen-passphrase",
                shard_frames=tuple(sheets),
            )
        )
