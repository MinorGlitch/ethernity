#!/usr/bin/env python3
from __future__ import annotations

import argparse

from ...core.models import ShardingConfig, SigningSeedMode
from ...crypto import DEFAULT_PASSPHRASE_WORDS, MNEMONIC_WORD_COUNTS
from ..api import prompt_choice, prompt_int, prompt_yes_no
from ..core.log import _warn


def prompt_passphrase_words() -> int:
    choices = {str(count): f"{count} words" for count in MNEMONIC_WORD_COUNTS}
    default = str(DEFAULT_PASSPHRASE_WORDS)
    value = prompt_choice(
        "Passphrase length",
        choices,
        default=default,
        help_text="Longer passphrases are stronger and easier to record.",
    )
    return int(value)


def _prompt_quorum(
    *,
    label: str,
    default_threshold: int,
    default_shares: int,
    default_help_text: str,
    threshold_help_text: str,
    shares_help_text: str,
) -> ShardingConfig:
    use_default = prompt_yes_no(
        f"Use the default quorum ({default_threshold} of {default_shares})",
        default=True,
        help_text=default_help_text,
    )
    if use_default:
        return ShardingConfig(threshold=default_threshold, shares=default_shares)
    threshold = prompt_int(
        f"{label} threshold (n)",
        minimum=1,
        help_text=threshold_help_text,
    )
    shares = prompt_int(
        f"{label} count (k)",
        minimum=threshold,
        help_text=shares_help_text,
    )
    return ShardingConfig(threshold=threshold, shares=shares)


def _confirm_or_prompt_quorum(
    *,
    label: str,
    threshold: int,
    shares: int,
    default_threshold: int,
    default_shares: int,
    default_help_text: str,
    threshold_help_text: str,
    shares_help_text: str,
    existing_help_text: str,
) -> ShardingConfig:
    use_existing = prompt_yes_no(
        f"Use provided {label.lower()} ({threshold} of {shares})",
        default=True,
        help_text=existing_help_text,
    )
    if use_existing:
        return ShardingConfig(threshold=threshold, shares=shares)
    return _prompt_quorum(
        label=label,
        default_threshold=default_threshold,
        default_shares=default_shares,
        default_help_text=default_help_text,
        threshold_help_text=threshold_help_text,
        shares_help_text=shares_help_text,
    )


def resolve_passphrase_sharding(
    *,
    args: argparse.Namespace | None,
) -> ShardingConfig | None:
    threshold = getattr(args, "shard_threshold", None) if args is not None else None
    shares = getattr(args, "shard_count", None) if args is not None else None
    default_threshold = 2
    default_shares = 3
    if threshold is not None or shares is not None:
        if threshold is None or shares is None:
            raise ValueError("both --shard-threshold and --shard-count are required")
        return _confirm_or_prompt_quorum(
            label="Shard",
            threshold=threshold,
            shares=shares,
            default_threshold=default_threshold,
            default_shares=default_shares,
            default_help_text="Pick a different split if you need more redundancy.",
            threshold_help_text="Minimum number of shard documents required to recover.",
            shares_help_text="Total number of shard documents to create.",
            existing_help_text="Choose no to configure a different quorum.",
        )

    enable_sharding = prompt_yes_no(
        "Split passphrase into shard documents",
        default=True,
        help_text="Recommended. You'll need a quorum of shard documents to recover.",
    )
    if not enable_sharding:
        return None
    return _prompt_quorum(
        label="Shard",
        default_threshold=default_threshold,
        default_shares=default_shares,
        default_help_text="Pick a different split if you need more redundancy.",
        threshold_help_text="Minimum number of shard documents required to recover.",
        shares_help_text="Total number of shard documents to create.",
    )


def resolve_signing_seed_mode(
    *,
    args: argparse.Namespace | None,
    sealed: bool,
    quiet: bool,
) -> SigningSeedMode:
    mode_arg = getattr(args, "signing_key_mode", None) if args is not None else None
    signing_seed_mode = SigningSeedMode(mode_arg) if mode_arg else SigningSeedMode.EMBEDDED
    if sealed:
        if signing_seed_mode == SigningSeedMode.SHARDED:
            _warn(
                "Signing-key sharding is disabled for sealed backups.",
                quiet=quiet,
            )
            signing_seed_mode = SigningSeedMode.EMBEDDED
        return signing_seed_mode
    if mode_arg is None:
        signing_choice = prompt_choice(
            "Signing key handling",
            {
                "embedded": ("Embedded in main document (default, easiest to mint new shards)"),
                "sharded": ("Separate signing-key shards (requires quorum to mint new shards)"),
            },
            default="embedded",
            help_text=(
                "Embedded stores the signing key inside the encrypted "
                "main document. Sharded keeps it only in separate "
                "signing-key shard PDFs."
            ),
        )
        signing_seed_mode = SigningSeedMode(signing_choice)
    return signing_seed_mode


def resolve_signing_seed_sharding(
    *,
    args: argparse.Namespace | None,
    signing_seed_mode: SigningSeedMode,
    passphrase_sharding: ShardingConfig,
) -> ShardingConfig | None:
    if signing_seed_mode != SigningSeedMode.SHARDED:
        return None
    sk_threshold = getattr(args, "signing_key_shard_threshold", None) if args is not None else None
    sk_count = getattr(args, "signing_key_shard_count", None) if args is not None else None
    default_threshold = passphrase_sharding.threshold
    default_shares = passphrase_sharding.shares
    if sk_threshold is not None or sk_count is not None:
        if sk_threshold is None or sk_count is None:
            raise ValueError(
                "both --signing-key-shard-threshold and --signing-key-shard-count are required"
            )
        return _confirm_or_prompt_quorum(
            label="Signing-key shard",
            threshold=sk_threshold,
            shares=sk_count,
            default_threshold=default_threshold,
            default_shares=default_shares,
            default_help_text="Pick a different split if you need more redundancy.",
            threshold_help_text=("Minimum signing-key shard documents needed to mint new shards."),
            shares_help_text="Total signing-key shard documents to create.",
            existing_help_text="Choose no to configure a different quorum.",
        )
    use_same = prompt_yes_no(
        "Use same quorum for signing-key shards",
        default=True,
        help_text="Choose no to set a different quorum for signing-key shards.",
    )
    if use_same:
        return None
    return _prompt_quorum(
        label="Signing-key shard",
        default_threshold=default_threshold,
        default_shares=default_shares,
        default_help_text="Pick a different split if you need more redundancy.",
        threshold_help_text=("Minimum signing-key shard documents needed to mint new shards."),
        shares_help_text="Total signing-key shard documents to create.",
    )
