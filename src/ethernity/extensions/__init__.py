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

"""Curated public helpers for extension build, discovery, staging, layout, and replay."""

from ethernity.extensions.build import (
    BuiltExtensionDocument,
    ExtensionBuildStats,
    build_extension_document,
    build_virtual_chunk_source,
    default_extension_chunker,
)
from ethernity.extensions.chain import (
    AuthenticatedExtensionChainLink,
    LogicalFileState,
    extract_root_logical_state,
    reconstruct_authenticated_latest_logical_state,
    validate_authenticated_extension_chain,
)
from ethernity.extensions.discovery import (
    EXTENSIONS_DIR_NAME,
    DiscoveredExtensionDirectory,
    DiscoveredExtensionMainCarrier,
    DiscoveredExtensionShardCarrier,
    ValidatedExtensionDiscovery,
    discover_extension_directories,
    discover_validated_extension_directories,
    extension_root_dir,
    is_extension_like_top_level_entry,
    payload_main_carriers,
)
from ethernity.extensions.layout import (
    ExtensionMainArtifactName,
    ExtensionShardArtifactName,
    build_extension_main_filename,
    build_extension_shard_filename,
    build_staging_dir_name,
    canonical_extension_dir_name,
    is_canonical_extension_dir_name,
    is_staging_dir_name,
    loose_extension_dir_name,
    parse_extension_dir_name,
    parse_extension_main_filename,
    parse_extension_shard_filename,
)
from ethernity.extensions.staging import (
    ExtensionPublishLayout,
    ExtensionPublishPolicy,
    PlannedStagedExtensionArtifacts,
    create_extension_staging_dir,
    create_loose_extension_staging_dir,
    create_staged_extension_artifact_plan,
    preflight_extension_publish_target,
    snapshot_staged_extension_dir,
)

__all__ = [
    "BuiltExtensionDocument",
    "EXTENSIONS_DIR_NAME",
    "DiscoveredExtensionDirectory",
    "DiscoveredExtensionMainCarrier",
    "DiscoveredExtensionShardCarrier",
    "ValidatedExtensionDiscovery",
    "ExtensionBuildStats",
    "AuthenticatedExtensionChainLink",
    "ExtensionMainArtifactName",
    "ExtensionPublishLayout",
    "ExtensionPublishPolicy",
    "ExtensionShardArtifactName",
    "LogicalFileState",
    "PlannedStagedExtensionArtifacts",
    "build_extension_document",
    "build_extension_main_filename",
    "build_extension_shard_filename",
    "build_staging_dir_name",
    "build_virtual_chunk_source",
    "canonical_extension_dir_name",
    "create_loose_extension_staging_dir",
    "create_staged_extension_artifact_plan",
    "create_extension_staging_dir",
    "default_extension_chunker",
    "discover_extension_directories",
    "discover_validated_extension_directories",
    "extension_root_dir",
    "extract_root_logical_state",
    "is_canonical_extension_dir_name",
    "is_extension_like_top_level_entry",
    "is_staging_dir_name",
    "loose_extension_dir_name",
    "parse_extension_dir_name",
    "parse_extension_main_filename",
    "parse_extension_shard_filename",
    "payload_main_carriers",
    "preflight_extension_publish_target",
    "reconstruct_authenticated_latest_logical_state",
    "snapshot_staged_extension_dir",
    "validate_authenticated_extension_chain",
]
