"""Canonical workflow inputs shared by adapters, preparation, and execution.

Paths accept strings or pathlib paths, including the stdin sentinel. Collections
are read-only sequences; input loaders normalize them when opening the sources.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ethernity.encoding.framing import Frame
from ethernity.workflows.shared.generation_options import (
    BackupRecoveryOptions,
    ReplacementRecoveryOptions,
)


@dataclass(frozen=True, slots=True)
class BackupRequest(BackupRecoveryOptions):
    config_path: str | Path | None = None
    paper_size: str | None = None
    design: str | None = None
    input_paths: Sequence[str | Path] = ()
    input_dirs: Sequence[str | Path] = ()
    base_dir: str | Path | None = None
    output_dir: str | Path | None = None
    qr_chunk_size: int | None = None
    passphrase: str | None = None
    passphrase_words: int | None = None
    layout_debug_dir: str | Path | None = None
    passphrase_generate: bool = False
    sealed: bool = False
    debug: bool = False
    debug_max_bytes: int = 0
    debug_reveal_secrets: bool = False
    quiet: bool = False


@dataclass(frozen=True, kw_only=True)
class RecoveryUnlockInputs:
    """Unlock and authentication inputs used when reading an existing backup."""

    passphrase: str | None = None
    shard_text_files: Sequence[str | Path] = ()
    shard_payload_files: Sequence[str | Path] = ()
    shard_scan_paths: Sequence[str | Path] = ()
    shard_frames: Sequence[Frame] = ()
    auth_text_file: str | Path | None = None
    auth_payloads_file: str | Path | None = None

    def recovery_request(self) -> RecoveryRequest:
        """Start a recovery request with the same unlock inputs."""

        return RecoveryRequest(
            passphrase=self.passphrase,
            shard_text_files=self.shard_text_files,
            shard_payload_files=self.shard_payload_files,
            shard_scan_paths=self.shard_scan_paths,
            shard_frames=self.shard_frames,
            auth_text_file=self.auth_text_file,
            auth_payloads_file=self.auth_payloads_file,
        )


@dataclass(frozen=True, slots=True)
class RecoveryRequest(RecoveryUnlockInputs):
    config_path: str | Path | None = None
    paper_size: str | None = None
    frames: Sequence[Frame] = ()
    recovery_text_file: str | Path | None = None
    payloads_file: str | Path | None = None
    scan_paths: Sequence[str | Path] = ()
    auth_frames: Sequence[Frame] = ()
    extension_index: int | None = None
    extension_doc_hash: str | None = None
    expected_head_doc_hash: str | None = None
    output_path: str | Path | None = None
    allow_unsigned: bool = False
    debug_max_bytes: int = 0
    debug_reveal_secrets: bool = False
    quiet: bool = False


@dataclass(frozen=True, slots=True)
class RebuildRequest(RecoveryUnlockInputs):
    config_path: str | Path | None = None
    paper_size: str | None = None
    design: str | None = None
    backup_folder: str | Path | None = None
    scan_paths: Sequence[str | Path] = ()
    output_dir: str | Path | None = None
    auth_frames: Sequence[Frame] = ()
    qr_chunk_size: int | None = None
    expected_head_doc_hash: str | None = None
    allow_stale_head: bool = False
    layout_debug_dir: str | Path | None = None
    quiet: bool = False


@dataclass(frozen=True, slots=True)
class ReplacementRecoveryRequest(ReplacementRecoveryOptions, RecoveryUnlockInputs):
    config_path: str | Path | None = None
    paper_size: str | None = None
    design: str | None = None
    frames: Sequence[Frame] = ()
    recovery_text_file: str | Path | None = None
    payloads_file: str | Path | None = None
    input_label: str | None = None
    input_detail: str | None = None
    scan_paths: Sequence[str | Path] = ()
    extension_index: int | None = None
    extension_doc_hash: str | None = None
    expected_head_doc_hash: str | None = None
    allow_stale_head: bool = False
    signing_key_shard_text_files: Sequence[str | Path] = ()
    signing_key_shard_payload_files: Sequence[str | Path] = ()
    signing_key_shard_scan_paths: Sequence[str | Path] = ()
    signing_key_shard_frames: Sequence[Frame] = ()
    output_dir: str | Path | None = None
    output_dir_existing_parent: bool = False
    layout_debug_dir: str | Path | None = None
    quiet: bool = False
