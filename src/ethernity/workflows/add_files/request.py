"""Typed request for the Add Files workflow."""

from __future__ import annotations

from dataclasses import dataclass

from ethernity.crypto.sharding import MAX_SHARES
from ethernity.encoding.framing import Frame
from ethernity.formats.extension_mode import UpdateMode


def validate_recovery_sheet_counts(threshold: int, sheet_count: int) -> None:
    """Validate one passphrase recovery-sheet quorum."""

    if not 1 <= threshold <= MAX_SHARES:
        raise ValueError(f"recovery threshold must be between 1 and {MAX_SHARES}")
    if not 1 <= sheet_count <= MAX_SHARES:
        raise ValueError(f"recovery sheet count must be between 1 and {MAX_SHARES}")
    if threshold > sheet_count:
        raise ValueError("recovery threshold cannot exceed recovery sheet count")


@dataclass(frozen=True)
class AddFilesRequest:
    """Adapter-neutral request to inspect, assess, or publish one extension."""

    config_path: str | None = None
    paper_size: str | None = None
    design: str | None = None
    recovery_text_file: str | None = None
    payloads_file: str | None = None
    scan_paths: tuple[str, ...] = ()
    frames: tuple[Frame, ...] = ()
    auth_text_file: str | None = None
    auth_payloads_file: str | None = None
    auth_frames: tuple[Frame, ...] = ()
    output_dir: str | None = None
    input_paths: tuple[str, ...] = ()
    input_directories: tuple[str, ...] = ()
    base_directory: str | None = None
    layout_debug_directory: str | None = None
    qr_chunk_size: int | None = None
    passphrase: str | None = None
    shard_fallback_files: tuple[str, ...] = ()
    shard_payload_files: tuple[str, ...] = ()
    shard_scan_paths: tuple[str, ...] = ()
    shard_frames: tuple[Frame, ...] = ()
    expected_head_doc_hash: str | None = None
    allow_stale_head: bool = False
    update_mode: UpdateMode | None = None
    create_recovery_sheets: bool = False
    recovery_threshold: int = 2
    recovery_sheet_count: int = 3
    quiet: bool = False

    def __post_init__(self) -> None:
        if self.update_mode is not None:
            object.__setattr__(self, "update_mode", UpdateMode(self.update_mode))
        for field_name in (
            "scan_paths",
            "frames",
            "auth_frames",
            "input_paths",
            "input_directories",
            "shard_fallback_files",
            "shard_payload_files",
            "shard_scan_paths",
            "shard_frames",
        ):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))

        expected_head = self.expected_head_doc_hash
        if expected_head is not None:
            normalized = expected_head.strip().lower()
            if len(normalized) == 64 and all(
                character in "0123456789abcdef" for character in normalized
            ):
                object.__setattr__(self, "expected_head_doc_hash", normalized)

        validate_recovery_sheet_counts(self.recovery_threshold, self.recovery_sheet_count)


__all__ = ["AddFilesRequest", "validate_recovery_sheet_counts"]
