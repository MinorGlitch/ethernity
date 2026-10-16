"""Typed execution results shared by task states and workflow implementations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ethernity.config import AppConfig
from ethernity.core.failures import FailureStage
from ethernity.core.models import DocumentPlan
from ethernity.workflows.backup.service import (
    execute_prepared_backup,
    prepare_backup_run,
)
from ethernity.workflows.rebuild.service import execute_rebuild_operation
from ethernity.workflows.recovery.models import RecoveryInspection
from ethernity.workflows.recovery.planning import inspect_from_request
from ethernity.workflows.recovery.service import execute_recover_plan, prepare_recover_plan
from ethernity.workflows.replacement_recovery.service import execute_replacement_recovery_operation
from ethernity.workflows.shared.events import CommandError
from ethernity.workflows.shared.file_inputs import InputFile
from ethernity.workflows.shared.operation_types import BackupResult
from ethernity.workflows.shared.requests import (
    BackupRequest,
    RebuildRequest,
    RecoveryRequest,
    ReplacementRecoveryRequest,
)


@dataclass(frozen=True, slots=True)
class BackupPreparation:
    """Adapter-neutral backup inputs used by the diagnostics view."""

    config: AppConfig
    plan: DocumentPlan
    input_files: tuple[InputFile, ...]
    input_origin: Literal["file", "directory", "mixed"]
    input_roots: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BackupExecutionResult:
    qr_path: Path
    recovery_path: Path
    shard_paths: tuple[Path, ...]
    signing_key_shard_paths: tuple[Path, ...]
    kit_index_path: Path | None = None
    signing_key_preserved: bool | None = None
    doc_hash: bytes | None = None


@dataclass(frozen=True, slots=True)
class RecoveryExecutionResult:
    written_paths: tuple[Path, ...]
    trust_basis: Literal["matched_expected_head", "internally_consistent", "unauthenticated"] = (
        "internally_consistent"
    )
    signing_key_verified: bool = False


@dataclass(frozen=True, slots=True)
class ReplacementRecoveryResult:
    shard_paths: tuple[Path, ...]
    signing_key_shard_paths: tuple[Path, ...]


class WorkflowExecutionError(Exception):
    """Stable adapter-neutral failure raised by an execution implementation."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        stage: FailureStage | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.stage = stage
        self.details = details or {}


def prepare_backup(request: BackupRequest) -> BackupPreparation:
    prepared = prepare_backup_run(request)
    return BackupPreparation(
        config=prepared.config,
        plan=prepared.plan,
        input_files=prepared.input_files,
        input_origin=prepared.input_origin,
        input_roots=prepared.input_roots,
    )


def execute_backup(request: BackupRequest) -> BackupExecutionResult:
    result = execute_prepared_backup(prepare_backup_run(request))
    return _backup_result(result)


def inspect_recovery(request: RecoveryRequest) -> RecoveryInspection:
    try:
        return inspect_from_request(request)
    except CommandError as exc:
        raise WorkflowExecutionError(
            code=exc.code, message=exc.message, stage=exc.stage, details=dict(exc.details)
        ) from exc


def execute_recovery(request: RecoveryRequest) -> RecoveryExecutionResult:
    plan = prepare_recover_plan(request)
    result = execute_recover_plan(
        plan,
        quiet=request.quiet,
        debug_max_bytes=request.debug_max_bytes,
        debug_reveal_secrets=request.debug_reveal_secrets,
    )
    return RecoveryExecutionResult(
        written_paths=tuple(Path(path) for path in result.written_paths),
        trust_basis=result.trust_basis,
        signing_key_verified=result.signing_key_verified,
    )


def execute_rebuild(request: RebuildRequest) -> BackupExecutionResult:
    result = execute_rebuild_operation(request)
    return _backup_result(result)


def execute_replacement_recovery(
    request: ReplacementRecoveryRequest,
) -> ReplacementRecoveryResult:
    result = execute_replacement_recovery_operation(request)
    return ReplacementRecoveryResult(
        shard_paths=tuple(Path(path) for path in result.shard_paths),
        signing_key_shard_paths=tuple(Path(path) for path in result.signing_key_shard_paths),
    )


def _backup_result(result: BackupResult) -> BackupExecutionResult:
    return BackupExecutionResult(
        qr_path=Path(result.qr_path),
        recovery_path=Path(result.recovery_path),
        shard_paths=tuple(Path(path) for path in result.shard_paths),
        signing_key_shard_paths=tuple(Path(path) for path in result.signing_key_shard_paths),
        kit_index_path=Path(result.kit_index_path) if result.kit_index_path is not None else None,
        signing_key_preserved=result.signing_key_preserved,
        doc_hash=result.doc_hash,
    )


__all__ = [
    "BackupExecutionResult",
    "BackupPreparation",
    "RecoveryExecutionResult",
    "ReplacementRecoveryResult",
    "WorkflowExecutionError",
    "execute_backup",
    "execute_rebuild",
    "execute_recovery",
    "execute_replacement_recovery",
    "inspect_recovery",
    "prepare_backup",
]
