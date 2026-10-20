"""Carrier assembly shared by recovery inspection and execution planning."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from ethernity.encoding.frame_sets import (
    deduplicate_auth_frames,
    deduplicate_frame_slots,
    split_main_and_auth_frames,
)
from ethernity.encoding.framing import Frame, FrameType
from ethernity.extensions.recovery import ImportedRecoveryDocument
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


@dataclass(frozen=True)
class LoadedRecoverySource:
    """Imported source bytes, including sheets needed by maintenance workflows."""

    frames: tuple[Frame, ...]
    extra_auth_frames: tuple[Frame, ...]
    documents: tuple[ImportedRecoveryDocument, ...]
    input_label: str | None
    input_detail: str | None

    @property
    def recovery_frames(self) -> tuple[Frame, ...]:
        return tuple(frame for frame in self.frames if frame.frame_type != FrameType.KEY_DOCUMENT)

    @property
    def sheet_frames(self) -> tuple[Frame, ...]:
        return tuple(frame for frame in self.frames if frame.frame_type == FrameType.KEY_DOCUMENT)

    def assembled_root(self, doc_id: bytes) -> AssembledRecoveryDocument:
        document = next((item for item in self.documents if item.doc_id == doc_id), None)
        if document is None:
            raise ValueError("Selected root is not part of the imported source.")
        frames = [frame for frame in self.recovery_frames if frame.doc_id == doc_id]
        extra_auth = self.extra_auth_frames
        if len(self.documents) > 1:
            extra_auth = tuple(frame for frame in extra_auth if frame.doc_id == doc_id)
        main, auth = split_main_and_auth_frames(deduplicate_frame_slots(frames))
        auth = deduplicate_auth_frames([*auth, *extra_auth])
        return AssembledRecoveryDocument(
            source=recovery_source_fields(self.input_label, self.input_detail, main, auth),
            ciphertext=document.ciphertext,
            doc_id=document.doc_id,
            doc_hash=document.doc_hash,
        )


@dataclass(frozen=True)
class LoadedRecoveryInputs:
    source: LoadedRecoverySource
    shard_frames: tuple[Frame, ...] = ()
    shard_fallback_files: tuple[str, ...] = ()
    shard_payload_files: tuple[str, ...] = ()
    shard_scan: tuple[str, ...] = ()


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
