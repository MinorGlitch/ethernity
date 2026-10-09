from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest

from ethernity.tasks import backup, models, rebuild
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.rebuild import RebuildTaskState
from ethernity.workflows import execution as workflow_execution
from ethernity.workflows.execution import BackupExecutionResult
from ethernity.workflows.shared import requests
from ethernity.workflows.shared.operation_types import BackupResult


def test_recovery_check_paths_require_explicit_metadata() -> None:
    result = models.TaskExecutionResult(
        status="succeeded",
        message="Documents created.",
        output_paths=(Path("qr_backup.pdf"), Path("shard-1-of-3.pdf")),
    )

    assert result.recovery_check_paths == ()


@pytest.mark.parametrize("task", ("backup", "rebuild"))
@pytest.mark.parametrize("doc_hash", (None, b"D" * 32), ids=("legacy", "known-identity"))
def test_backup_adapters_preserve_the_new_document_identity(
    task: Literal["backup", "rebuild"],
    doc_hash: bytes | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    produced = BackupResult(
        doc_id=b"D" * 8,
        qr_path="custom-name.pdf",
        recovery_path="guide.pdf",
        shard_paths=(),
        signing_key_shard_paths=(),
        passphrase_used="secret",
        source_head_doc_hash=(b"S" * 32).hex(),
        doc_hash=doc_hash,
    )
    if task == "backup":
        monkeypatch.setattr(workflow_execution, "prepare_backup_run", lambda _args: object())
        monkeypatch.setattr(
            workflow_execution, "execute_prepared_backup", lambda _prepared: produced
        )
        result = workflow_execution.execute_backup(requests.BackupRequest())
    else:
        monkeypatch.setattr(
            workflow_execution, "execute_rebuild_operation", lambda _request: produced
        )
        result = workflow_execution.execute_rebuild(requests.RebuildRequest())

    assert result.doc_hash == doc_hash


@pytest.mark.parametrize("task", ("backup", "rebuild"))
@pytest.mark.parametrize("with_sheets", (False, True), ids=("phrase", "all-sheets"))
def test_backup_producers_mark_carriers_by_role_without_guessing_filenames(
    task: Literal["backup", "rebuild"],
    with_sheets: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    passphrase_sheets = (
        (tmp_path / "envelope-red.pdf", tmp_path / "envelope-blue.pdf", tmp_path / "third.pdf")
        if with_sheets
        else ()
    )
    signing_sheets = (
        (tmp_path / "key-holder-one.pdf", tmp_path / "key-holder-two.pdf") if with_sheets else ()
    )
    execution = BackupExecutionResult(
        qr_path=tmp_path / "user-chosen-name.pdf",
        recovery_path=tmp_path / "shard-looking-plaintext-guide.pdf",
        shard_paths=passphrase_sheets,
        signing_key_shard_paths=signing_sheets,
        kit_index_path=tmp_path / "main-looking-index.pdf",
        doc_hash=b"D" * 32,
    )
    state: BackupTaskState | RebuildTaskState
    if task == "backup":
        state = BackupTaskState(
            input_paths=[tmp_path / "source.txt"],
            output_dir=tmp_path / "output",
            recovery_method="recommended_shards" if with_sheets else "single_phrase",
            signing_key_mode="sharded" if with_sheets else "embedded",
            signing_key_shard_threshold=2 if with_sheets else None,
            signing_key_shard_count=2 if with_sheets else None,
        )
        monkeypatch.setattr(backup, "execute_backup", lambda _request: execution)
    else:
        state = RebuildTaskState(
            backup_folder=tmp_path / "old-backup",
            allow_stale_head=True,
            passphrase="secret",
            output_dir=tmp_path / "output",
        )
        monkeypatch.setattr(rebuild, "execute_rebuild", lambda _request: execution)

    result = state.execute()

    assert result.ok
    assert result.output_paths == (
        execution.qr_path,
        execution.recovery_path,
        *passphrase_sheets,
        *signing_sheets,
        execution.kit_index_path,
    )
    assert result.recovery_check_paths == (
        execution.qr_path,
        *passphrase_sheets,
        *signing_sheets,
    )
    assert (
        next(detail.value for detail in result.details if detail.key == "doc_hash")
        == (b"D" * 32).hex()
    )
