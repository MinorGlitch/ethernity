"""Carrier assembly shared by recovery inspection and execution planning."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from ethernity.crypto.document_identity import doc_id_and_hash_from_ciphertext
from ethernity.encoding.chunking import reassemble_payload
from ethernity.encoding.frame_sets import (
    deduplicate_auth_frames,
    deduplicate_frame_slots,
    split_main_and_auth_frames,
)
from ethernity.encoding.framing import Frame, FrameType
from ethernity.workflows.recovery.constants import RECOVERY_SCAN_LABEL


@dataclass(frozen=True)
class RecoverySourceFields:
    input_label: str | None
    input_detail: str | None
    main_frames: tuple[Frame, ...]
    auth_frames: tuple[Frame, ...]
    shard_frames: tuple[Frame, ...]
    shard_fallback_files: tuple[str, ...]
    shard_payloads_file: tuple[str, ...]
    shard_scan: tuple[str, ...]

    def with_shards(
        self,
        frames: Sequence[Frame],
        fallback_files: Sequence[str],
        payload_files: Sequence[str],
        scan_paths: Sequence[str],
    ) -> RecoverySourceFields:
        return replace(
            self,
            shard_frames=tuple(frames),
            shard_fallback_files=tuple(fallback_files),
            shard_payloads_file=tuple(payload_files),
            shard_scan=tuple(scan_paths),
        )


@dataclass(frozen=True)
class AssembledRecoveryDocument:
    source: RecoverySourceFields
    ciphertext: bytes
    doc_id: bytes
    doc_hash: bytes


def recovery_source_fields(
    input_label: str | None,
    input_detail: str | None,
    main_frames: Sequence[Frame],
    auth_frames: Sequence[Frame],
    shard_frames: Sequence[Frame] = (),
    shard_fallback_files: Sequence[str] = (),
    shard_payloads_file: Sequence[str] = (),
    shard_scan: Sequence[str] = (),
) -> RecoverySourceFields:
    return RecoverySourceFields(
        input_label=input_label,
        input_detail=input_detail,
        main_frames=tuple(main_frames),
        auth_frames=tuple(auth_frames),
        shard_frames=tuple(shard_frames),
        shard_fallback_files=tuple(shard_fallback_files),
        shard_payloads_file=tuple(shard_payloads_file),
        shard_scan=tuple(shard_scan),
    )


def require_recovery_frames(frames: Sequence[Frame], input_label: str | None) -> None:
    if frames:
        return
    hint = (
        "Check the scan path and image quality, then try again."
        if input_label == RECOVERY_SCAN_LABEL
        else "Check the input path and try again."
    )
    raise ValueError(f"no backup data found. {hint}")


def assemble_recovery_document(
    frames: Sequence[Frame],
    extra_auth_frames: Sequence[Frame],
    *,
    input_label: str | None,
    input_detail: str | None,
) -> AssembledRecoveryDocument:
    main_frames, auth_frames = split_main_and_auth_frames(deduplicate_frame_slots(list(frames)))
    if extra_auth_frames:
        auth_frames = deduplicate_auth_frames([*auth_frames, *extra_auth_frames])
    ciphertext = reassemble_payload(main_frames, expected_frame_type=FrameType.MAIN_DOCUMENT)
    doc_id, doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
    return AssembledRecoveryDocument(
        source=recovery_source_fields(input_label, input_detail, main_frames, auth_frames),
        ciphertext=ciphertext,
        doc_id=doc_id,
        doc_hash=doc_hash,
    )
