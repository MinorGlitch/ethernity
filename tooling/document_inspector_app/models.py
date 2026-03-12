from __future__ import annotations

from dataclasses import dataclass

from ethernity.encoding.framing import Frame

from .bootstrap import SRC_ROOT as _SRC_ROOT  # noqa: F401


@dataclass(frozen=True)
class FrameRecord:
    frame: Frame
    detail: dict[str, object]
    detail_text: str
    raw_text: str
    cbor_text: str
    payload_text: str
    fallback_text: str


@dataclass(frozen=True)
class FileRecord:
    path: str
    size: int
    sha256: str
    preview_kind: str
    preview: str
    data: bytes


@dataclass(frozen=True)
class RecoveredSecretRecord:
    label: str
    status: str
    summary: str
    detail_text: str
    export_name: str
    export_text: str


@dataclass(frozen=True)
class InspectionResult:
    source_label: str
    input_mode: str
    parsed_frame_count: int
    deduped_frame_count: int
    warnings: tuple[str, ...]
    summary_text: str
    diagnostics_text: str
    normalized_payload_text: str
    combined_fallback_text: str
    manifest_text: str
    manifest_json_text: str | None
    frame_records: tuple[FrameRecord, ...]
    files: tuple[FileRecord, ...]
    recovered_secrets: tuple[RecoveredSecretRecord, ...]
    report_json: str


@dataclass(frozen=True)
class BatchReportEntry:
    source_label: str
    source_path: str | None
    frame_count: int
    doc_ids: tuple[str, ...]
    frame_types: tuple[str, ...]
    warnings: tuple[str, ...]
    error: str | None


__all__ = [
    "BatchReportEntry",
    "FileRecord",
    "FrameRecord",
    "InspectionResult",
    "RecoveredSecretRecord",
]
