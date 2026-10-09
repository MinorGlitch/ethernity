#!/usr/bin/env python3
# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>.

"""Shared types and constants for Add Files execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ethernity.config import AppConfig, QrPayloadCodec
from ethernity.encoding.framing import Frame
from ethernity.extensions.build import VerifiedExtensionCandidate
from ethernity.extensions.chain import ValidatedChainState
from ethernity.extensions.staging import StagedExtensionPaths
from ethernity.render.types import FallbackSummary
from ethernity.workflows.add_files.planning import ResolvedAddFilesPlan
from ethernity.workflows.add_files.request import AddFilesRequest
from ethernity.workflows.shared.input_scope import SelectedInputScope


@dataclass(frozen=True)
class PreparedAddFilesRun:
    """Validated state required to publish one Add Files update."""

    request: AddFilesRequest
    plan: ResolvedAddFilesPlan
    selected_input: SelectedInputScope
    validated_chain: ValidatedChainState
    chain_document_count: int
    chain_ciphertext_bytes: int
    chain_decoded_chunk_bytes: int
    encryption_passphrase: str
    source_frames: tuple[Frame, ...] = ()

    @property
    def root_doc_hash(self) -> bytes:
        return self.plan.parent.root_doc_hash

    @property
    def parent_doc_hash(self) -> bytes:
        return self.plan.parent.head_doc_hash

    @property
    def next_index(self) -> int:
        return self.plan.parent.head_index + 1

    @property
    def signing_seed(self) -> bytes:
        return self.plan.signing_key.signing_seed

    @property
    def changed_paths(self) -> tuple[str, ...]:
        return self.plan.diff.changed_paths

    @property
    def new_paths(self) -> tuple[str, ...]:
        return self.plan.diff.new_paths

    @property
    def unchanged_paths(self) -> tuple[str, ...]:
        return self.plan.diff.unchanged_paths


@dataclass(frozen=True)
class EncryptedExtension:
    """Verified update document, encrypted bytes, and document identity."""

    built: VerifiedExtensionCandidate
    plaintext: bytes
    ciphertext: bytes
    doc_id: bytes
    doc_hash: bytes


@dataclass(frozen=True)
class ExtensionPublication:
    """Encrypted update and staged output paths for publication."""

    prepared: PreparedAddFilesRun
    encrypted: EncryptedExtension
    paths: StagedExtensionPaths


@dataclass(frozen=True)
class ExtensionRenderResult:
    """Fallback data returned after rendering the staged extension documents."""

    recovery_document_fallback_frames: tuple[Frame, ...]
    recovery_document_fallback_summary: FallbackSummary | None = None


@dataclass(frozen=True)
class PublishedExtensionResult:
    """Published extension paths after staged validation succeeds."""

    index: int
    doc_id: bytes
    doc_hash: bytes
    final_dir: Path
    qr_document_path: Path
    recovery_document_path: Path
    parent_head_index: int | None = None
    parent_head_doc_hash: str | None = None
    expected_head_doc_hash: str | None = None
    recovery_frames: tuple[Frame, ...] = ()


@dataclass(frozen=True)
class ExecutedAddFilesRun:
    """Published Add Files update and the authenticated state used to create it."""

    prepared: PreparedAddFilesRun
    output_settings: ExtensionOutputSettings
    publish: ExtensionPublication
    result: PublishedExtensionResult


@dataclass(frozen=True)
class ExtensionOutputSettings:
    """Resolved render and publish settings for Add Files execution."""

    config: AppConfig
    qr_chunk_size: int
    qr_payload_codec: QrPayloadCodec
    layout_debug_dir: str | None
    sign_pub: bytes


__all__ = [
    "EncryptedExtension",
    "ExecutedAddFilesRun",
    "ExtensionPublication",
    "PreparedAddFilesRun",
    "PublishedExtensionResult",
    "ExtensionRenderResult",
    "ExtensionOutputSettings",
]
