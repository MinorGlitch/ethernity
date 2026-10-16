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

from ethernity.crypto import MNEMONIC_WORD_COUNTS
from ethernity.workflows.shared.quorum import validate_quorum, validate_quorum_pair
from ethernity.workflows.shared.requests import BackupRequest

__all__ = ["validate_backup_request"]


def validate_backup_request(args: BackupRequest) -> None:
    if args.passphrase == "":
        raise ValueError("passphrase cannot be empty")
    if (
        args.passphrase is not None
        and args.shard_count is None
        and not args.passphrase.isprintable()
    ):
        raise ValueError(
            "directly printed passphrase must contain only manually enterable printable text"
        )
    if args.passphrase and args.passphrase_generate:
        raise ValueError("use either --passphrase or --generate-passphrase, not both")
    if args.qr_chunk_size is not None and args.qr_chunk_size <= 0:
        raise ValueError("qr chunk size must be a positive integer")
    _validate_backup_sharding(args)
    if args.passphrase_words is not None:
        _validate_passphrase_words(args.passphrase_words)


def _validate_backup_sharding(args: BackupRequest) -> None:
    if args.signing_key_mode is not None and args.signing_key_mode not in ("embedded", "sharded"):
        raise ValueError("signing key mode must be 'embedded' or 'sharded'")
    if args.signing_key_shard_threshold is not None or args.signing_key_shard_count is not None:
        if args.signing_key_shard_threshold is None or args.signing_key_shard_count is None:
            raise ValueError(
                "both --signing-key-shard-threshold and --signing-key-shard-count are required"
            )
        if args.signing_key_mode != "sharded":
            raise ValueError("signing key shard quorum requires --signing-key-mode sharded")
        validate_quorum(
            args.signing_key_shard_threshold,
            args.signing_key_shard_count,
            label="signing key shard",
        )
    if args.signing_key_mode == "sharded":
        if args.shard_threshold is None or args.shard_count is None:
            raise ValueError("signing key sharding requires passphrase sharding")
    validate_quorum_pair(
        args.shard_threshold,
        args.shard_count,
        pair_label="--shard-threshold and --shard-count",
    )


def _validate_passphrase_words(words: int) -> None:
    if words not in MNEMONIC_WORD_COUNTS:
        allowed = ", ".join(str(count) for count in MNEMONIC_WORD_COUNTS)
        raise ValueError(f"passphrase words must be one of {allowed}")
