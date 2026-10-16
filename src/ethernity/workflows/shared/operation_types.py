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

from __future__ import annotations

from dataclasses import dataclass

from ethernity.workflows.shared.file_inputs import InputFile as InputFile


@dataclass(frozen=True)
class BackupResult:
    doc_id: bytes
    qr_path: str
    recovery_path: str
    shard_paths: tuple[str, ...]
    signing_key_shard_paths: tuple[str, ...]
    passphrase_used: str | None
    kit_index_path: str | None = None
    signing_key_preserved: bool | None = None
    source_head_index: int | None = None
    source_head_doc_hash: str | None = None
    expected_head_doc_hash: str | None = None
    freshness_scope: str | None = None
    doc_hash: bytes | None = None


@dataclass(frozen=True)
class ReplacementRecoveryOperationResult:
    doc_id: bytes
    doc_hash: bytes
    output_dir: str
    shard_paths: tuple[str, ...]
    signing_key_shard_paths: tuple[str, ...]
    signing_key_source: str
    notes: tuple[str, ...] = ()
    selected_extension_index: int | None = None
    selected_extension_doc_hash: str | None = None
