"""Check generated documents by recovering their scanned data into temporary storage."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import TemporaryDirectory

from ethernity.core.execution_control import cancellation_point
from ethernity.crypto.sharding import recover_passphrase
from ethernity.workflows.execution import inspect_recovery
from ethernity.workflows.recovery.models import RecoveryInspection
from ethernity.workflows.recovery.planning import plan_from_inspection
from ethernity.workflows.recovery.service import execute_recover_plan
from ethernity.workflows.recovery.session import RecoverySession
from ethernity.workflows.shared import issue_codes
from ethernity.workflows.shared.requests import RecoveryRequest

__all__ = [
    "GeneratedRecoveryCheckRequest",
    "GeneratedRecoveryCheckResult",
    "GeneratedRecoveryPassphraseRequired",
    "check_generated_recovery",
]


@dataclass(frozen=True, slots=True)
class GeneratedRecoveryCheckRequest:
    documents: tuple[Path, ...]
    passphrase: str | None = None
    config_path: Path | None = None
    expected_head_doc_hash: str | None = None
    base_request: RecoveryRequest | None = None


@dataclass(frozen=True, slots=True)
class GeneratedRecoveryCheckResult:
    file_count: int
    total_bytes: int
    recovery_sheet_count: int


class GeneratedRecoveryPassphraseRequired(ValueError):
    """The supplied documents require the passphrase printed in the recovery document."""


def check_generated_recovery(
    request: GeneratedRecoveryCheckRequest, *, session: RecoverySession | None = None
) -> GeneratedRecoveryCheckResult:
    """Scan and recover supplied documents without retaining recovered plaintext."""
    if not request.documents:
        raise ValueError("Choose backup documents to check.")
    cancellation_point()
    session = session or RecoverySession()
    base = request.base_request or RecoveryRequest(quiet=True)
    config_path = request.config_path if request.config_path is not None else base.config_path
    expected_head = (
        request.expected_head_doc_hash
        if request.expected_head_doc_hash is not None
        else base.expected_head_doc_hash
    )
    inspection_request = replace(
        base,
        config_path=config_path,
        scan_paths=(*base.scan_paths, *request.documents),
        passphrase=None,
        expected_head_doc_hash=expected_head,
        output_path=None,
        allow_unsigned=False,
    )
    inspection = inspect_recovery(inspection_request, session=session)
    has_sheets = inspection.unlock.mode == "shards"
    passphrase = request.passphrase if request.passphrase is not None else base.passphrase
    if not has_sheets and passphrase:
        inspection = inspect_recovery(
            replace(inspection_request, passphrase=passphrase), session=session
        )
    _require_ready_inspection(inspection)
    if has_sheets:
        inspection = _minimum_root_sheet_quorum(inspection)
    cancellation_point()

    with TemporaryDirectory(prefix="ethernity-recovery-check-") as temporary_directory:
        plan = plan_from_inspection(
            inspection,
            replace(inspection_request, output_path=Path(temporary_directory) / "recovered"),
        )
        recovered = execute_recover_plan(plan, quiet=True, session=session)
        cancellation_point()
        if not recovered.written_paths:
            raise ValueError("No files were recovered from the supplied documents.")
        return GeneratedRecoveryCheckResult(
            file_count=len(recovered.written_paths),
            total_bytes=sum(Path(path).stat().st_size for path in recovered.written_paths),
            recovery_sheet_count=len(inspection.source.shard_frames) if has_sheets else 0,
        )


def _require_ready_inspection(inspection: RecoveryInspection) -> None:
    other_issues = [
        issue
        for issue in inspection.blocking_issues
        if issue.code != issue_codes.PASSPHRASE_REQUIRED
    ]
    if other_issues:
        raise ValueError(other_issues[0].message)
    if inspection.unlock.mode == "missing":
        raise GeneratedRecoveryPassphraseRequired(
            "Enter the passphrase printed in the recovery document to check these PDFs."
        )
    if not inspection.unlock.satisfied:
        raise ValueError("The supplied recovery sheets cannot unlock this backup.")


def _minimum_root_sheet_quorum(inspection: RecoveryInspection) -> RecoveryInspection:
    threshold = inspection.unlock.required_shard_threshold
    if threshold is None:
        raise ValueError("The recovery sheet quorum could not be determined.")
    sheets = sorted(
        (
            item
            for item in inspection.unlock.validated_shards
            if item.frame.doc_id == inspection.doc_id
            and item.payload.doc_hash == inspection.doc_hash
        ),
        key=lambda item: item.payload.share_index,
    )
    if len(sheets) < threshold:
        raise ValueError(f"Need at least {threshold} recovery sheets bound to the root backup.")
    selected = sheets[:threshold]
    # Every supplied sheet was checked above. Actually reconstruct with only the
    # minimum quorum, so a saved phrase or extra sheets cannot mask a failed check.
    passphrase = recover_passphrase([item.payload for item in selected], verify_signatures=False)
    if passphrase != inspection.unlock.resolved_passphrase:
        raise ValueError("The minimum recovery sheet quorum recovered a different passphrase.")
    return replace(
        inspection,
        source=replace(inspection.source, shard_frames=tuple(item.frame for item in selected)),
        unlock=replace(
            inspection.unlock,
            validated_shards=tuple(selected),
            validated_shard_count=len(selected),
            resolved_passphrase=passphrase,
        ),
    )
