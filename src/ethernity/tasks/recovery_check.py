"""Check generated documents by recovering their scanned data into temporary storage."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import TemporaryDirectory

from ethernity.crypto.sharding import KEY_TYPE_PASSPHRASE, decode_shard_payload
from ethernity.encoding.framing import Frame
from ethernity.workflows.execution import (
    execute_recovery,
    inspect_recovery,
)
from ethernity.workflows.recovery import frame_inputs, inputs as recovery_inputs
from ethernity.workflows.recovery.models import RecoveryInspection
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
    request: GeneratedRecoveryCheckRequest,
) -> GeneratedRecoveryCheckResult:
    """Scan and recover supplied documents without retaining recovered plaintext."""
    if not request.documents:
        raise ValueError("Choose backup documents to check.")
    scanned_frames = frame_inputs.frames_from_scan([str(path) for path in request.documents])
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
        frames=(*base.frames, *scanned_frames),
        passphrase=None,
        expected_head_doc_hash=expected_head,
        output_path=None,
        allow_unsigned=False,
    )
    inspection = inspect_recovery(inspection_request)
    sheet_frames = recovery_inputs.document_sheet_frames(
        list(inspection.shard_frames), key_type=KEY_TYPE_PASSPHRASE
    )
    passphrase = request.passphrase if request.passphrase is not None else base.passphrase
    if not sheet_frames and passphrase:
        inspection = inspect_recovery(replace(inspection_request, passphrase=passphrase))
    _require_ready_inspection(inspection)
    selected_sheets = _minimum_root_sheet_quorum(inspection) if sheet_frames else ()

    with TemporaryDirectory(prefix="ethernity-recovery-check-") as temporary_directory:
        recovered = execute_recovery(
            RecoveryRequest(
                config_path=config_path,
                frames=inspection.source_frames,
                auth_frames=inspection.source_extra_auth_frames,
                shard_frames=selected_sheets,
                passphrase=None if selected_sheets else passphrase,
                extension_index=base.extension_index,
                extension_doc_hash=base.extension_doc_hash,
                expected_head_doc_hash=expected_head,
                output_path=Path(temporary_directory) / "recovered",
                quiet=True,
            )
        )
        if not recovered.written_paths:
            raise ValueError("No files were recovered from the supplied documents.")
        return GeneratedRecoveryCheckResult(
            file_count=len(recovered.written_paths),
            total_bytes=sum(path.stat().st_size for path in recovered.written_paths),
            recovery_sheet_count=len(selected_sheets),
        )


def _require_ready_inspection(inspection: RecoveryInspection) -> None:
    other_issues = [
        issue
        for issue in inspection.blocking_issues
        if issue.get("code") != issue_codes.PASSPHRASE_REQUIRED
    ]
    if other_issues:
        raise ValueError(str(other_issues[0].get("message", "Document recovery check failed.")))
    if inspection.unlock.mode == "missing":
        raise GeneratedRecoveryPassphraseRequired(
            "Enter the passphrase printed in the recovery document to check these PDFs."
        )
    if not inspection.unlock.satisfied:
        raise ValueError("The supplied recovery sheets cannot unlock this backup.")


def _minimum_root_sheet_quorum(inspection: RecoveryInspection) -> tuple[Frame, ...]:
    threshold = inspection.unlock.required_shard_threshold
    if threshold is None:
        raise ValueError("The recovery sheet quorum could not be determined.")
    unique_sheets: dict[int, Frame] = {}
    for frame in inspection.shard_frames:
        payload = decode_shard_payload(frame.data)
        if (
            frame.doc_id == inspection.doc_id
            and payload.doc_hash == inspection.doc_hash
            and payload.key_type == KEY_TYPE_PASSPHRASE
        ):
            unique_sheets.setdefault(payload.share_index, frame)
    if len(unique_sheets) < threshold:
        raise ValueError(f"Need at least {threshold} recovery sheets bound to the root backup.")
    return tuple(unique_sheets[index] for index in sorted(unique_sheets)[:threshold])
