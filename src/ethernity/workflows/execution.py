"""Typed execution boundary shared by task states and workflow implementations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeVar

from ethernity.config import AppConfig, apply_render_style, load_app_config
from ethernity.core.models import DocumentPlan
from ethernity.encoding.framing import Frame
from ethernity.workflows.backup.service import (
    execute_prepared_backup,
    prepare_backup_run,
)
from ethernity.workflows.doctor.service import reconcile_publication_transactions
from ethernity.workflows.kit import service as kit_service
from ethernity.workflows.rebuild.service import run_compact
from ethernity.workflows.recovery.models import RecoveryInspection
from ethernity.workflows.recovery.planning import inspect_from_args
from ethernity.workflows.recovery.service import execute_recover_plan, prepare_recover_plan
from ethernity.workflows.replacement_recovery.service import execute_mint
from ethernity.workflows.shared.events import CommandError
from ethernity.workflows.shared.file_inputs import InputFile
from ethernity.workflows.shared.operation_types import (
    BackupArgs,
    BackupResult,
    CompactArgs,
    MintArgs,
    RecoverArgs,
)

DEFAULT_KIT_OUTPUT = "recovery_kit_qr.pdf"
_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class BackupRequest:
    config_path: Path | None = None
    paper_size: str | None = None
    design: str | None = None
    input_paths: tuple[Path, ...] = ()
    input_dirs: tuple[Path, ...] = ()
    base_dir: Path | None = None
    output_dir: Path | None = None
    qr_chunk_size: int | None = None
    passphrase: str | None = None
    passphrase_words: int | None = None
    shard_threshold: int | None = None
    shard_count: int | None = None
    signing_key_mode: Literal["embedded", "sharded"] | None = None
    signing_key_shard_threshold: int | None = None
    signing_key_shard_count: int | None = None


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


@dataclass(frozen=True, slots=True)
class RecoveryRequest:
    config_path: Path | None = None
    paper_size: str | None = None
    frames: tuple[Frame, ...] = ()
    recovery_text_file: Path | None = None
    payloads_file: Path | None = None
    scan_paths: tuple[Path, ...] = ()
    passphrase: str | None = None
    shard_text_files: tuple[Path, ...] = ()
    shard_payload_files: tuple[Path, ...] = ()
    shard_scan_paths: tuple[Path, ...] = ()
    shard_frames: tuple[Frame, ...] = ()
    auth_text_file: Path | None = None
    auth_payloads_file: Path | None = None
    auth_frames: tuple[Frame, ...] = ()
    extension_index: int | None = None
    extension_doc_hash: str | None = None
    expected_head_doc_hash: str | None = None
    output_path: Path | None = None
    allow_unsigned: bool = False
    resource_intensive_compatibility_recovery: bool = False


@dataclass(frozen=True, slots=True)
class RecoveryExecutionResult:
    written_paths: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class RebuildRequest:
    config_path: Path | None = None
    paper_size: str | None = None
    design: str | None = None
    backup_folder: Path | None = None
    scan_paths: tuple[Path, ...] = ()
    output_dir: Path | None = None
    shard_text_files: tuple[Path, ...] = ()
    shard_payload_files: tuple[Path, ...] = ()
    shard_scan_paths: tuple[Path, ...] = ()
    shard_frames: tuple[Frame, ...] = ()
    auth_text_file: Path | None = None
    auth_payloads_file: Path | None = None
    auth_frames: tuple[Frame, ...] = ()
    qr_chunk_size: int | None = None
    passphrase: str | None = None
    expected_head_doc_hash: str | None = None
    allow_stale_head: bool = False


@dataclass(frozen=True, slots=True)
class ReplacementRecoveryRequest:
    config_path: Path | None = None
    paper_size: str | None = None
    design: str | None = None
    frames: tuple[Frame, ...] = ()
    recovery_text_file: Path | None = None
    payloads_file: Path | None = None
    input_label: str | None = None
    input_detail: str | None = None
    scan_paths: tuple[Path, ...] = ()
    passphrase: str | None = None
    shard_text_files: tuple[Path, ...] = ()
    shard_payload_files: tuple[Path, ...] = ()
    shard_scan_paths: tuple[Path, ...] = ()
    shard_frames: tuple[Frame, ...] = ()
    auth_text_file: Path | None = None
    auth_payloads_file: Path | None = None
    extension_index: int | None = None
    extension_doc_hash: str | None = None
    expected_head_doc_hash: str | None = None
    allow_stale_head: bool = False
    signing_key_shard_text_files: tuple[Path, ...] = ()
    signing_key_shard_payload_files: tuple[Path, ...] = ()
    signing_key_shard_scan_paths: tuple[Path, ...] = ()
    signing_key_shard_frames: tuple[Frame, ...] = ()
    output_dir: Path | None = None
    shard_threshold: int | None = None
    shard_count: int | None = None
    signing_key_shard_threshold: int | None = None
    signing_key_shard_count: int | None = None
    passphrase_replacement_count: int | None = None
    signing_key_replacement_count: int | None = None
    mint_passphrase_shards: bool = True
    mint_signing_key_shards: bool = True


@dataclass(frozen=True, slots=True)
class ReplacementRecoveryResult:
    shard_paths: tuple[Path, ...]
    signing_key_shard_paths: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class KitRequest:
    output_path: Path
    config_path: Path | None
    paper_size: str
    design: str
    variant: Literal["lean", "scanner"]
    chunk_size: int | None


@dataclass(frozen=True, slots=True)
class KitExecutionResult:
    output_path: Path
    chunk_count: int
    bytes_total: int


@dataclass(frozen=True, slots=True)
class DoctorRequest:
    backup_folder: Path
    passphrase: str
    repair: bool


@dataclass(frozen=True, slots=True)
class DoctorTransactionResult:
    path: Path
    status: str
    action: str


@dataclass(frozen=True, slots=True)
class DoctorExecutionResult:
    authenticated_head_index: int
    authenticated_head_hash: str
    transactions: tuple[DoctorTransactionResult, ...]


class WorkflowExecutionError(Exception):
    """Stable adapter-neutral failure raised by an execution implementation."""

    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def prepare_backup(request: BackupRequest) -> BackupPreparation:
    prepared = prepare_backup_run(_backup_args(request))
    return BackupPreparation(
        config=prepared.config,
        plan=prepared.plan,
        input_files=prepared.input_files,
        input_origin=prepared.input_origin,
        input_roots=prepared.input_roots,
    )


def execute_backup(request: BackupRequest) -> BackupExecutionResult:
    result = execute_prepared_backup(prepare_backup_run(_backup_args(request)))
    return _backup_result(result)


def inspect_recovery(request: RecoveryRequest) -> RecoveryInspection:
    try:
        return inspect_from_args(_recovery_args(request))
    except CommandError as exc:
        raise WorkflowExecutionError(code=exc.code, message=exc.message) from exc


def execute_recovery(request: RecoveryRequest) -> RecoveryExecutionResult:
    args = _recovery_args(request)
    plan = prepare_recover_plan(args)
    result = execute_recover_plan(plan, quiet=True)
    return RecoveryExecutionResult(
        written_paths=tuple(Path(path) for path in result.written_paths),
    )


def execute_rebuild(request: RebuildRequest) -> BackupExecutionResult:
    result = run_compact(
        CompactArgs(
            config=_path_text(request.config_path),
            paper=request.paper_size,
            design=request.design,
            root_dir=_path_text(request.backup_folder),
            scan=_path_list(request.scan_paths),
            output_dir=_path_text(request.output_dir),
            shard_fallback_file=_path_list(request.shard_text_files),
            shard_payloads_file=_path_list(request.shard_payload_files),
            shard_scan=_path_list(request.shard_scan_paths),
            shard_frames=_list_or_none(request.shard_frames),
            auth_fallback_file=_path_text(request.auth_text_file),
            auth_payloads_file=_path_text(request.auth_payloads_file),
            auth_frames=_list_or_none(request.auth_frames),
            qr_chunk_size=request.qr_chunk_size,
            passphrase=request.passphrase,
            expected_head_doc_hash=request.expected_head_doc_hash,
            allow_stale_head=request.allow_stale_head,
            quiet=True,
        )
    )
    return _backup_result(result)


def execute_replacement_recovery(
    request: ReplacementRecoveryRequest,
) -> ReplacementRecoveryResult:
    result = execute_mint(
        MintArgs(
            config=_path_text(request.config_path),
            paper=request.paper_size,
            design=request.design,
            fallback_file=_path_text(request.recovery_text_file),
            payloads_file=_path_text(request.payloads_file),
            frames=_list_or_none(request.frames),
            input_label=request.input_label,
            input_detail=request.input_detail,
            scan=_path_list(request.scan_paths),
            passphrase=request.passphrase,
            shard_fallback_file=_path_list(request.shard_text_files),
            shard_payloads_file=_path_list(request.shard_payload_files),
            shard_scan=_path_list(request.shard_scan_paths),
            shard_frames=_list_or_none(request.shard_frames),
            auth_fallback_file=_path_text(request.auth_text_file),
            auth_payloads_file=_path_text(request.auth_payloads_file),
            extension_index=request.extension_index,
            extension_doc_hash=request.extension_doc_hash,
            expected_head_doc_hash=request.expected_head_doc_hash,
            allow_stale_head=request.allow_stale_head,
            signing_key_shard_fallback_file=_path_list(request.signing_key_shard_text_files),
            signing_key_shard_payloads_file=_path_list(request.signing_key_shard_payload_files),
            signing_key_shard_scan=_path_list(request.signing_key_shard_scan_paths),
            signing_key_shard_frames=_list_or_none(request.signing_key_shard_frames),
            output_dir=_path_text(request.output_dir),
            output_dir_existing_parent=False,
            shard_threshold=request.shard_threshold,
            shard_count=request.shard_count,
            signing_key_shard_threshold=request.signing_key_shard_threshold,
            signing_key_shard_count=request.signing_key_shard_count,
            passphrase_replacement_count=request.passphrase_replacement_count,
            signing_key_replacement_count=request.signing_key_replacement_count,
            mint_passphrase_shards=request.mint_passphrase_shards,
            mint_signing_key_shards=request.mint_signing_key_shards,
            quiet=True,
        )
    )
    return ReplacementRecoveryResult(
        shard_paths=tuple(Path(path) for path in result.shard_paths),
        signing_key_shard_paths=tuple(Path(path) for path in result.signing_key_shard_paths),
    )


def execute_kit(request: KitRequest) -> KitExecutionResult:
    config = load_app_config(request.config_path, paper_size=request.paper_size)
    config = apply_render_style(config, request.design)
    result = kit_service.render_kit_qr_document(
        output_path=request.output_path,
        config=config,
        variant=request.variant,
        chunk_size=request.chunk_size,
    )
    return KitExecutionResult(
        output_path=result.output_path,
        chunk_count=result.chunk_count,
        bytes_total=result.bytes_total,
    )


def execute_doctor(request: DoctorRequest) -> DoctorExecutionResult:
    result = reconcile_publication_transactions(
        request.backup_folder,
        passphrase=request.passphrase,
        repair=request.repair,
    )
    return DoctorExecutionResult(
        authenticated_head_index=result.authenticated_head_index,
        authenticated_head_hash=result.authenticated_head_hash,
        transactions=tuple(
            DoctorTransactionResult(
                path=item.path,
                status=item.status,
                action=item.action,
            )
            for item in result.transactions
        ),
    )


def _backup_args(request: BackupRequest) -> BackupArgs:
    return BackupArgs(
        config=_path_text(request.config_path),
        paper=request.paper_size,
        design=request.design,
        input=_path_list(request.input_paths),
        input_dir=_path_list(request.input_dirs),
        base_dir=_path_text(request.base_dir),
        output_dir=_path_text(request.output_dir),
        output_dir_existing_parent=False,
        qr_chunk_size=request.qr_chunk_size,
        passphrase=request.passphrase,
        passphrase_words=request.passphrase_words,
        shard_threshold=request.shard_threshold,
        shard_count=request.shard_count,
        signing_key_mode=request.signing_key_mode,
        signing_key_shard_threshold=request.signing_key_shard_threshold,
        signing_key_shard_count=request.signing_key_shard_count,
        assume_yes=True,
        quiet=True,
    )


def _recovery_args(request: RecoveryRequest) -> RecoverArgs:
    return RecoverArgs(
        config=_path_text(request.config_path),
        paper=request.paper_size,
        fallback_file=_path_text(request.recovery_text_file),
        payloads_file=_path_text(request.payloads_file),
        scan=_path_list(request.scan_paths),
        frames=_list_or_none(request.frames),
        passphrase=request.passphrase,
        shard_fallback_file=_path_list(request.shard_text_files),
        shard_payloads_file=_path_list(request.shard_payload_files),
        shard_scan=_path_list(request.shard_scan_paths),
        shard_frames=_list_or_none(request.shard_frames),
        auth_fallback_file=_path_text(request.auth_text_file),
        auth_payloads_file=_path_text(request.auth_payloads_file),
        auth_frames=_list_or_none(request.auth_frames),
        extension_index=request.extension_index,
        extension_doc_hash=request.extension_doc_hash,
        expected_head_doc_hash=request.expected_head_doc_hash,
        output=_path_text(request.output_path),
        allow_unsigned=request.allow_unsigned,
        resource_intensive_compatibility_recovery=(
            request.resource_intensive_compatibility_recovery
        ),
        assume_yes=True,
        quiet=True,
    )


def _backup_result(result: BackupResult) -> BackupExecutionResult:
    return BackupExecutionResult(
        qr_path=Path(result.qr_path),
        recovery_path=Path(result.recovery_path),
        shard_paths=tuple(Path(path) for path in result.shard_paths),
        signing_key_shard_paths=tuple(Path(path) for path in result.signing_key_shard_paths),
        kit_index_path=Path(result.kit_index_path) if result.kit_index_path is not None else None,
    )


def _path_text(value: Path | None) -> str | None:
    return str(value) if value is not None else None


def _path_list(values: tuple[Path, ...]) -> list[str] | None:
    return [str(value) for value in values] or None


def _list_or_none(values: tuple[_T, ...]) -> list[_T] | None:
    return list(values) or None


__all__ = [
    "DEFAULT_KIT_OUTPUT",
    "BackupExecutionResult",
    "BackupPreparation",
    "BackupRequest",
    "DoctorExecutionResult",
    "DoctorRequest",
    "DoctorTransactionResult",
    "KitExecutionResult",
    "KitRequest",
    "RebuildRequest",
    "RecoveryExecutionResult",
    "RecoveryRequest",
    "ReplacementRecoveryRequest",
    "ReplacementRecoveryResult",
    "WorkflowExecutionError",
    "execute_backup",
    "execute_doctor",
    "execute_kit",
    "execute_rebuild",
    "execute_recovery",
    "execute_replacement_recovery",
    "inspect_recovery",
    "prepare_backup",
]
