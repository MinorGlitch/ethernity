"""Typed input contract for the extension workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ethernity.encoding.framing import Frame


@dataclass(frozen=True)
class ExtensionRequest:
    """Adapter-neutral request to inspect, assess, or publish one extension."""

    config_path: str | None = None
    paper_size: str | None = None
    design: str | None = None
    publish_root: str | None = None
    scan_paths: tuple[str, ...] = ()
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
    unlock_policy: Literal["self-contained", "reuse-root"] | None = None
    shard_threshold: int | None = None
    shard_count: int | None = None
    signing_key_mode: Literal["not-stored", "sharded"] | None = None
    signing_key_shard_threshold: int | None = None
    signing_key_shard_count: int | None = None
    expected_head_doc_hash: str | None = None
    allow_stale_head: bool = False
    quiet: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "scan_paths",
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
