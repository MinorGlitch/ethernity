#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from ...crypto import MNEMONIC_WORD_COUNTS


def _validate_backup_args(args: argparse.Namespace) -> None:
    if args.passphrase and args.passphrase_generate:
        raise ValueError("use either --passphrase or --generate-passphrase, not both")
    signing_key_mode = getattr(args, "signing_key_mode", None)
    if signing_key_mode is not None and signing_key_mode not in ("embedded", "sharded"):
        raise ValueError("signing key mode must be 'embedded' or 'sharded'")
    signing_key_shard_threshold = getattr(args, "signing_key_shard_threshold", None)
    signing_key_shard_count = getattr(args, "signing_key_shard_count", None)
    if signing_key_shard_threshold is not None or signing_key_shard_count is not None:
        if signing_key_shard_threshold is None or signing_key_shard_count is None:
            raise ValueError(
                "both --signing-key-shard-threshold and --signing-key-shard-count are required"
            )
        if signing_key_mode != "sharded":
            raise ValueError("signing key shard quorum requires --signing-key-mode sharded")
        if signing_key_shard_threshold < 1:
            raise ValueError("signing key shard threshold must be >= 1")
        if signing_key_shard_count < signing_key_shard_threshold:
            raise ValueError("signing key shard count must be >= signing key shard threshold")
    if signing_key_mode == "sharded":
        if args.shard_threshold is None or args.shard_count is None:
            raise ValueError("signing key sharding requires passphrase sharding")
    if args.shard_threshold or args.shard_count:
        if not args.shard_threshold or not args.shard_count:
            raise ValueError("both --shard-threshold and --shard-count are required")
    if args.shard_threshold is not None and args.shard_count is not None:
        if args.shard_threshold < 1:
            raise ValueError("shard threshold must be >= 1")
        if args.shard_count < args.shard_threshold:
            raise ValueError("shard count must be >= shard threshold")
    if args.base_dir and not Path(args.base_dir).exists():
        raise ValueError("base dir not found")
    if args.base_dir and not Path(args.base_dir).is_dir():
        raise ValueError("base dir is not a directory")
    passphrase_words = getattr(args, "passphrase_words", None)
    if passphrase_words is not None:
        _validate_passphrase_words(passphrase_words)


def _validate_passphrase_words(words: int) -> None:
    if words not in MNEMONIC_WORD_COUNTS:
        allowed = ", ".join(str(count) for count in MNEMONIC_WORD_COUNTS)
        raise ValueError(f"passphrase words must be one of {allowed}")
