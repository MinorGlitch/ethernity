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

from pathlib import Path

from ...crypto import MNEMONIC_WORD_COUNTS
from .types import BackupArgs

MAX_SHARDS = 255


def _validate_backup_args(args: BackupArgs) -> None:
    if args.passphrase and args.passphrase_generate:
        raise ValueError("use either --passphrase or --generate-passphrase, not both")
    if args.qr_chunk_size is not None and args.qr_chunk_size <= 0:
        raise ValueError("qr chunk size must be a positive integer")
    if args.signing_key_mode is not None and args.signing_key_mode not in ("embedded", "sharded"):
        raise ValueError("signing key mode must be 'embedded' or 'sharded'")
    if args.signing_key_shard_threshold is not None or args.signing_key_shard_count is not None:
        if args.signing_key_shard_threshold is None or args.signing_key_shard_count is None:
            raise ValueError(
                "both --signing-key-shard-threshold and --signing-key-shard-count are required"
            )
        if args.signing_key_mode != "sharded":
            raise ValueError("signing key shard quorum requires --signing-key-mode sharded")
        if args.signing_key_shard_threshold < 1:
            raise ValueError("signing key shard threshold must be >= 1")
        if args.signing_key_shard_threshold > MAX_SHARDS:
            raise ValueError(f"signing key shard threshold must be <= {MAX_SHARDS}")
        if args.signing_key_shard_count < args.signing_key_shard_threshold:
            raise ValueError("signing key shard count must be >= signing key shard threshold")
        if args.signing_key_shard_count > MAX_SHARDS:
            raise ValueError(f"signing key shard count must be <= {MAX_SHARDS}")
    if args.signing_key_mode == "sharded":
        if args.shard_threshold is None or args.shard_count is None:
            raise ValueError("signing key sharding requires passphrase sharding")
    if args.shard_threshold is not None or args.shard_count is not None:
        if args.shard_threshold is None or args.shard_count is None:
            raise ValueError("both --shard-threshold and --shard-count are required")
    if args.shard_threshold is not None and args.shard_count is not None:
        if args.shard_threshold < 1:
            raise ValueError("shard threshold must be >= 1")
        if args.shard_threshold > MAX_SHARDS:
            raise ValueError(f"shard threshold must be <= {MAX_SHARDS}")
        if args.shard_count < args.shard_threshold:
            raise ValueError("shard count must be >= shard threshold")
        if args.shard_count > MAX_SHARDS:
            raise ValueError(f"shard count must be <= {MAX_SHARDS}")
    if args.base_dir and not Path(args.base_dir).exists():
        raise ValueError("base dir not found")
    if args.base_dir and not Path(args.base_dir).is_dir():
        raise ValueError("base dir is not a directory")
    if args.passphrase_words is not None:
        _validate_passphrase_words(args.passphrase_words)


def _validate_passphrase_words(words: int) -> None:
    if words not in MNEMONIC_WORD_COUNTS:
        allowed = ", ".join(str(count) for count in MNEMONIC_WORD_COUNTS)
        raise ValueError(f"passphrase words must be one of {allowed}")
