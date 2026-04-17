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

"""Shared types and constants for extend execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ethernity.cli.features.extend.planning import ExtendInspection
from ethernity.cli.features.extend.scope import SelectedExtendScope
from ethernity.cli.shared.types import ExtendArgs
from ethernity.config import AppConfig, QrPayloadCodec
from ethernity.crypto import sharding as sharding_module
from ethernity.extensions.build import BuiltExtensionDocument
from ethernity.extensions.chain import LogicalFileState
from ethernity.extensions.staging import ExtensionPublishPolicy, PlannedStagedExtensionArtifacts
from ethernity.formats.extension_envelope import ExtensionChunkingProfile

EXTENSION_INPUT_REQUIRED = "EXTENSION_INPUT_REQUIRED"
EXTENSION_NO_CHANGES = "EXTENSION_NO_CHANGES"
EXTENSION_INVALID_POLICY = "EXTENSION_INVALID_POLICY"
EXTENSION_MAIN_CARRIER_INVALID = "EXTENSION_MAIN_CARRIER_INVALID"
EXTENSION_SHARD_CARRIER_INVALID = "EXTENSION_SHARD_CARRIER_INVALID"


@dataclass(frozen=True)
class PreparedExtendRun:
    """Validated preflight state for a future extend execution."""

    args: ExtendArgs
    inspection: ExtendInspection
    loaded_scope: SelectedExtendScope
    current_state: tuple[LogicalFileState, ...]
    encryption_passphrase: str
    root_doc_hash: bytes
    parent_doc_hash: bytes
    next_index: int
    signing_seed: bytes
    chunking: ExtensionChunkingProfile
    input_origin: str
    input_roots: tuple[str, ...]
    changed_paths: tuple[str, ...]
    new_paths: tuple[str, ...]
    unchanged_paths: tuple[str, ...]


@dataclass(frozen=True)
class EncryptedPreparedExtension:
    """Assembled and encrypted extension payload ready for render/staging."""

    built: BuiltExtensionDocument
    plaintext: bytes
    ciphertext: bytes
    doc_id: bytes
    doc_hash: bytes


@dataclass(frozen=True)
class PreparedExtensionPublishPlan:
    """Execution-grade extension plan with encrypted payload and staging targets."""

    prepared: PreparedExtendRun
    encrypted: EncryptedPreparedExtension
    publish_policy: ExtensionPublishPolicy
    artifacts: PlannedStagedExtensionArtifacts


@dataclass(frozen=True)
class RenderedExtensionArtifacts:
    """Expected shard payloads rendered for the staged extension."""

    passphrase_shards: tuple[sharding_module.ShardPayload, ...]
    signing_key_shards: tuple[sharding_module.ShardPayload, ...]
    expected_recovery_fallback_lines: tuple[str, ...]


@dataclass(frozen=True)
class PublishedExtensionResult:
    """Promoted extension artifacts after staged validation succeeds."""

    index: int
    doc_id: bytes
    doc_hash: bytes
    final_dir: Path
    qr_document_path: Path
    recovery_document_path: Path
    recovery_kit_index_path: Path | None
    shard_paths: tuple[Path, ...]
    signing_key_shard_paths: tuple[Path, ...]


@dataclass(frozen=True)
class ExecutedExtendRun:
    """Full extend execution outcome including prepared state and published artifacts."""

    prepared: PreparedExtendRun
    runtime: ResolvedExtendRuntime
    publish: PreparedExtensionPublishPlan
    result: PublishedExtensionResult


@dataclass(frozen=True)
class ResolvedExtendRuntime:
    """Resolved render and publish settings for an extension execution."""

    config: AppConfig
    qr_chunk_size: int
    qr_payload_codec: QrPayloadCodec
    layout_debug_dir: str | None
    publish_policy: ExtensionPublishPolicy
    passphrase_shard_threshold: int | None
    recovery_quorum_threshold: int | None
    recovery_quorum_shares: int | None
    signing_key_shard_threshold: int | None
    sign_pub: bytes
    kit_index_template_path: Path | None
    reuse_root_unlock: bool


@dataclass(frozen=True)
class InheritedRootPublishPolicy:
    """Publish-policy details inferred from the writable root backup directory."""

    require_recovery_kit_index: bool
    passphrase_shard_threshold: int | None
    passphrase_shard_count: int
    signing_key_shard_threshold: int | None
    signing_key_shard_count: int


ExtensionArtifactRenderer = Callable[[PreparedExtensionPublishPlan], object | None]
ExtensionArtifactPostValidator = Callable[[PreparedExtensionPublishPlan, object | None], None]


__all__ = [
    "EncryptedPreparedExtension",
    "ExecutedExtendRun",
    "EXTENSION_INPUT_REQUIRED",
    "EXTENSION_INVALID_POLICY",
    "EXTENSION_MAIN_CARRIER_INVALID",
    "EXTENSION_NO_CHANGES",
    "EXTENSION_SHARD_CARRIER_INVALID",
    "ExtensionArtifactPostValidator",
    "ExtensionArtifactRenderer",
    "InheritedRootPublishPolicy",
    "PreparedExtensionPublishPlan",
    "PreparedExtendRun",
    "PublishedExtensionResult",
    "RenderedExtensionArtifacts",
    "ResolvedExtendRuntime",
]
