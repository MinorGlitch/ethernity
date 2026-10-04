from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest

from ethernity.app.execution import ReviewedTask
from ethernity.app.recovery_check_requests import (
    generated_recovery_request,
    printed_recovery_request,
)
from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.models import TaskExecutionResult, TaskResultDetail
from ethernity.tasks.rebuild import RebuildTaskState


def test_generated_update_check_keeps_ancestry_and_pins_new_head(tmp_path: Path) -> None:
    parent_hash = "11" * 32
    new_hash = "22" * 32
    state = AddFilesTaskState(
        source_paths=[tmp_path / "original.pdf"],
        payloads_file=tmp_path / "updates.bin",
        recovery_documents=[tmp_path / "root-sheet.pdf"],
        auth_text_file=tmp_path / "signature.txt",
        passphrase="remembered phrase",
        expected_head_doc_hash=parent_hash,
    )
    reviewed = _reviewed(state)
    result = TaskExecutionResult(
        status="succeeded",
        message="Update created.",
        output_paths=(
            tmp_path / "update.pdf",
            tmp_path / "recovery-guide.pdf",
            tmp_path / "sheet.pdf",
            tmp_path / "index.html",
        ),
        recovery_check_paths=(tmp_path / "update.pdf", tmp_path / "sheet.pdf"),
        details=(TaskResultDetail(key="doc_hash", label="Fingerprint", value=new_hash),),
    )
    request = generated_recovery_request(reviewed, result)
    assert request.documents == result.recovery_check_paths
    assert request.expected_head_doc_hash == new_hash
    assert request.base_request is not None
    assert request.base_request.scan_paths == (tmp_path / "original.pdf",)
    assert request.base_request.payloads_file == state.payloads_file
    assert request.base_request.auth_text_file == state.auth_text_file
    assert request.base_request.shard_scan_paths == tuple(state.recovery_documents)
    assert request.base_request.expected_head_doc_hash is None


def test_generated_check_requires_explicit_carriers_without_filename_fallback(
    tmp_path: Path,
) -> None:
    reviewed = _reviewed(AddFilesTaskState())
    result = TaskExecutionResult(
        status="succeeded",
        message="Created.",
        output_paths=(tmp_path / "qr_document.pdf", tmp_path / "recovery-sheet.pdf"),
    )
    assert generated_recovery_request(reviewed, result).documents == ()


def test_generated_check_preserves_typed_carriers_without_guessing_filenames(
    tmp_path: Path,
) -> None:
    carriers = (tmp_path / "first-page.pdf", tmp_path / "second-page.pdf")
    result = TaskExecutionResult(
        status="succeeded",
        message="Created.",
        output_paths=(*carriers, tmp_path / "qr_document.pdf"),
        recovery_check_paths=carriers,
    )
    assert generated_recovery_request(_reviewed(AddFilesTaskState()), result).documents == carriers


def test_print_check_uses_only_physical_scans(tmp_path: Path) -> None:
    state = AddFilesTaskState(
        source_paths=[tmp_path / "generated-original.pdf"],
        passphrase="remembered phrase",
    )
    result = TaskExecutionResult(
        status="succeeded",
        message="Created.",
        output_paths=(tmp_path / "generated-update.pdf",),
        recovery_check_paths=(tmp_path / "generated-update.pdf",),
    )
    scans = (tmp_path / "photographed-backup.png", tmp_path / "photographed-sheet.png")
    request = printed_recovery_request(_reviewed(state), result, scans)
    assert request.documents == scans
    assert request.base_request is None
    assert request.passphrase is None


@pytest.mark.parametrize("task", ("backup", "rebuild"))
def test_root_document_checks_pin_new_result_identity(
    task: Literal["backup", "rebuild"], tmp_path: Path
) -> None:
    new_hash = "42" * 32
    state: BackupTaskState | RebuildTaskState = (
        BackupTaskState()
        if task == "backup"
        else RebuildTaskState(expected_head_doc_hash="13" * 32)
    )
    reviewed = ReviewedTask.capture(task, state)
    carrier = tmp_path / "arbitrary-created-document.pdf"
    result = TaskExecutionResult(
        status="succeeded",
        message="Created.",
        output_paths=(carrier,),
        recovery_check_paths=(carrier,),
        details=(TaskResultDetail(key="doc_hash", label="Full fingerprint", value=new_hash),),
    )
    generated = generated_recovery_request(reviewed, result)
    printed = printed_recovery_request(reviewed, result, (tmp_path / "printout.png",))
    assert generated.expected_head_doc_hash == new_hash
    assert printed.expected_head_doc_hash == new_hash
    assert printed.documents == (tmp_path / "printout.png",)


def _reviewed(state: AddFilesTaskState) -> ReviewedTask:
    # Only the task snapshot is consumed by the request mapper.
    return ReviewedTask.capture("add_files", state)
