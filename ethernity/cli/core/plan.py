#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from ...crypto import MNEMONIC_WORD_COUNTS
from ...core.models import DocumentMode


def _infer_mode(args: argparse.Namespace) -> DocumentMode:
    if args.recipient or args.recipients_file or args.generate_identity:
        return DocumentMode.RECIPIENT
    if args.passphrase or args.passphrase_generate:
        return DocumentMode.PASSPHRASE
    return DocumentMode.PASSPHRASE


def _validate_backup_args(mode: DocumentMode, args: argparse.Namespace, recipients: list[str]) -> None:
    if args.passphrase and args.passphrase_generate:
        raise ValueError("use either --passphrase or --generate-passphrase, not both")
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
        if mode == DocumentMode.RECIPIENT:
            raise ValueError("passphrase word count is only valid in passphrase mode")
        _validate_passphrase_words(passphrase_words)
    if mode == DocumentMode.RECIPIENT:
        if args.passphrase or args.passphrase_generate:
            raise ValueError("passphrase options are not valid in recipient mode")
        if args.generate_identity and recipients:
            raise ValueError("use either --generate-identity or --recipient/--recipients-file")
    if mode == DocumentMode.PASSPHRASE:
        if args.generate_identity or recipients:
            raise ValueError("recipient options are not valid in passphrase mode")


def _validate_passphrase_words(words: int) -> None:
    if words not in MNEMONIC_WORD_COUNTS:
        allowed = ", ".join(str(count) for count in MNEMONIC_WORD_COUNTS)
        raise ValueError(f"passphrase words must be one of {allowed}")
