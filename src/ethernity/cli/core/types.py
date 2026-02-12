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
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class InputFile:
    source_path: Path | None
    relative_path: str
    data: bytes
    mtime: int | None


@dataclass(frozen=True)
class BackupResult:
    doc_id: bytes
    qr_path: str
    recovery_path: str
    shard_paths: tuple[str, ...]
    signing_key_shard_paths: tuple[str, ...]
    passphrase_used: str | None
    kit_index_path: str | None = None


@dataclass
class BackupArgs:
    """Typed container for backup command arguments."""

    config: str | None = None
    paper: str | None = None
    design: str | None = None
    input: list[str] | None = None
    input_dir: list[str] | None = None
    base_dir: str | None = None
    output_dir: str | None = None
    qr_chunk_size: int | None = None
    passphrase: str | None = None
    passphrase_generate: bool = False
    passphrase_words: int | None = None
    sealed: bool = False
    shard_threshold: int | None = None
    shard_count: int | None = None
    signing_key_mode: Literal["embedded", "sharded"] | None = None
    signing_key_shard_threshold: int | None = None
    signing_key_shard_count: int | None = None
    debug: bool = False
    debug_max_bytes: int = 0
    quiet: bool = False


@dataclass
class RecoverArgs:
    """Typed container for recover command arguments."""

    config: str | None = None
    paper: str | None = None
    fallback_file: str | None = None
    payloads_file: str | None = None
    scan: list[str] | None = None
    passphrase: str | None = None
    shard_fallback_file: list[str] | None = None
    shard_dir: str | None = None
    shard_payloads_file: list[str] | None = None
    auth_fallback_file: str | None = None
    auth_payloads_file: str | None = None
    output: str | None = None
    allow_unsigned: bool = False
    assume_yes: bool = False
    quiet: bool = False
