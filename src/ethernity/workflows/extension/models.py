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

"""Shared types and constants for extension execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TypeAlias

from ethernity.config import AppConfig, QrPayloadCodec
from ethernity.crypto import sharding as sharding_module
from ethernity.encoding.framing import Frame
from ethernity.extensions.build import VerifiedExtensionCandidate
from ethernity.extensions.chain import LogicalFileState, ValidatedChainState
from ethernity.extensions.staging import ExtensionPublishPolicy, PlannedStagedExtensionArtifacts
from ethernity.formats.extension_envelope import ExtensionChunkingProfile
from ethernity.render.types import RenderFallbackProof
from ethernity.workflows.extension.planning import ResolvedExtensionPlan
from ethernity.workflows.extension.request import ExtensionRequest
from ethernity.workflows.extension.scope import SelectedExtendScope

EXTENSION_INPUT_REQUIRED = "EXTENSION_INPUT_REQUIRED"
EXTENSION_NO_CHANGES = "EXTENSION_NO_CHANGES"
EXTENSION_INVALID_POLICY = "EXTENSION_INVALID_POLICY"
EXTENSION_KIT_CARRIER_INVALID = "EXTENSION_KIT_CARRIER_INVALID"
EXTENSION_MAIN_CARRIER_INVALID = "EXTENSION_MAIN_CARRIER_INVALID"
EXTENSION_SHARD_CARRIER_INVALID = "EXTENSION_SHARD_CARRIER_INVALID"
EXTENSION_TOO_LARGE = "EXTENSION_TOO_LARGE"


@dataclass(frozen=True)
class PreparedExtendRun:
    """Validated preflight state for a future extend execution."""

    args: ExtensionRequest
    plan: ResolvedExtensionPlan
    loaded_scope: SelectedExtendScope
    current_state: tuple[LogicalFileState, ...]
    validated_chain_state: ValidatedChainState
    chain_document_count: int
    chain_ciphertext_bytes: int
    chain_decoded_chunk_bytes: int
    encryption_passphrase: str
    chunking: ExtensionChunkingProfile
    root_passphrase_shard_threshold: int | None
    root_passphrase_shard_count: int
    input_origin: str
    input_roots: tuple[str, ...]
    unlock_passphrase_shard_threshold: int | None = None
    unlock_passphrase_shard_count: int = 0

    @property
    def root_doc_hash(self) -> bytes:
        return self.plan.lineage.root_doc_hash

    @property
    def parent_doc_hash(self) -> bytes:
        return self.plan.lineage.head_doc_hash

    @property
    def next_index(self) -> int:
        return self.plan.lineage.head_index + 1

    @property
    def signing_seed(self) -> bytes:
        return self.plan.authority.signing_seed

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
class EncryptedPreparedExtension:
    """Assembled and encrypted extension payload ready for render/staging."""

    built: VerifiedExtensionCandidate
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
    recovery_document_fallback_frames: tuple[Frame, ...]
    recovery_document_fallback_proof: RenderFallbackProof | None = None


@dataclass(frozen=True)
class PublishedExtensionResult:
    """Promoted extension artifacts after staged validation succeeds."""

    index: int
    doc_id: bytes
    doc_hash: bytes
    final_dir: Path
    qr_document_path: Path
    recovery_document_path: Path
    recovery_kit_path: Path
    recovery_kit_index_path: Path | None
    shard_paths: tuple[Path, ...]
    signing_key_shard_paths: tuple[Path, ...]
    root_passphrase_shard_threshold: int | None = None
    root_passphrase_shard_count: int = 0
    parent_head_index: int | None = None
    parent_head_doc_hash: str | None = None
    expected_head_doc_hash: str | None = None
    publish_root: Path | None = None


@dataclass(frozen=True)
class ExecutedExtendRun:
    """Full extend execution outcome including prepared state and published artifacts."""

    prepared: PreparedExtendRun
    runtime: ResolvedExtendRuntime
    publish: PreparedExtensionPublishPlan
    result: PublishedExtensionResult


@dataclass(frozen=True)
class ExtensionPassphraseShards:
    """Extension-local passphrase shards unlock this extension."""

    threshold: int
    share_count: int


@dataclass(frozen=True)
class ReuseRootPassphraseShards:
    """Root passphrase shards unlock this extension."""

    threshold: int
    share_count: int


PassphraseStoragePolicy: TypeAlias = ExtensionPassphraseShards | ReuseRootPassphraseShards


@dataclass(frozen=True)
class SigningKeyNotStored:
    """Extension signing private key is not stored in extension artifacts."""


@dataclass(frozen=True)
class ExtensionSigningKeyShards:
    """Extension-local shards store root/chain signing authority recovery material."""

    threshold: int
    share_count: int


SigningKeyStoragePolicy: TypeAlias = SigningKeyNotStored | ExtensionSigningKeyShards


def publish_policy_from_storage(
    *,
    require_recovery_kit_index: bool,
    passphrase: PassphraseStoragePolicy,
    signing_key: SigningKeyStoragePolicy,
) -> ExtensionPublishPolicy:
    """Convert resolved storage policy into the staging artifact contract."""

    passphrase_shard_count = (
        passphrase.share_count if isinstance(passphrase, ExtensionPassphraseShards) else 0
    )
    signing_key_shard_count = (
        signing_key.share_count if isinstance(signing_key, ExtensionSigningKeyShards) else 0
    )
    return ExtensionPublishPolicy(
        require_recovery_kit_index=require_recovery_kit_index,
        passphrase_shard_count=passphrase_shard_count,
        signing_key_shard_count=signing_key_shard_count,
    )


@dataclass(frozen=True)
class ResolvedExtendRuntime:
    """Resolved render and publish settings for an extension execution."""

    config: AppConfig
    qr_chunk_size: int
    qr_payload_codec: QrPayloadCodec
    layout_debug_dir: str | None
    passphrase: PassphraseStoragePolicy
    signing_key: SigningKeyStoragePolicy
    sign_pub: bytes
    kit_index_style: str | None

    def to_publish_policy(self) -> ExtensionPublishPolicy:
        return publish_policy_from_storage(
            require_recovery_kit_index=self.kit_index_style is not None,
            passphrase=self.passphrase,
            signing_key=self.signing_key,
        )


@dataclass(frozen=True)
class ResolvedExtendPolicy:
    """Resolved extension shard and unlock policy."""

    require_recovery_kit_index: bool
    passphrase: PassphraseStoragePolicy
    signing_key: SigningKeyStoragePolicy

    def to_publish_policy(self) -> ExtensionPublishPolicy:
        return publish_policy_from_storage(
            require_recovery_kit_index=self.require_recovery_kit_index,
            passphrase=self.passphrase,
            signing_key=self.signing_key,
        )


ExtensionArtifactRenderer = Callable[[PreparedExtensionPublishPlan], RenderedExtensionArtifacts]
ExtensionArtifactPostValidator = Callable[
    [PreparedExtensionPublishPlan, RenderedExtensionArtifacts],
    None,
]


__all__ = [
    "EncryptedPreparedExtension",
    "ExecutedExtendRun",
    "EXTENSION_INPUT_REQUIRED",
    "EXTENSION_INVALID_POLICY",
    "EXTENSION_MAIN_CARRIER_INVALID",
    "EXTENSION_NO_CHANGES",
    "EXTENSION_SHARD_CARRIER_INVALID",
    "EXTENSION_TOO_LARGE",
    "ExtensionPassphraseShards",
    "ExtensionSigningKeyShards",
    "ExtensionArtifactPostValidator",
    "ExtensionArtifactRenderer",
    "PassphraseStoragePolicy",
    "PreparedExtensionPublishPlan",
    "PreparedExtendRun",
    "PublishedExtensionResult",
    "RenderedExtensionArtifacts",
    "ResolvedExtendPolicy",
    "ResolvedExtendRuntime",
    "ReuseRootPassphraseShards",
    "SigningKeyNotStored",
    "SigningKeyStoragePolicy",
    "publish_policy_from_storage",
]
