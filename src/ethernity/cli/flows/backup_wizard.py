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

from ...core.models import ShardingConfig, SigningSeedMode
from ...crypto import DEFAULT_PASSPHRASE_WORDS, MNEMONIC_WORD_COUNTS
from ..api import prompt_choice, prompt_int, prompt_yes_no
from ..core.log import _warn
from ..core.types import BackupArgs

# Common quorum presets with descriptions
QUORUM_PRESETS = {
    "2of3": ("2 of 3 (Recommended)", 2, 3, "Lose any 1 document and still recover"),
    "3of5": ("3 of 5 (Higher security)", 3, 5, "Require 3 shards; can lose 2"),
    "2of5": ("2 of 5 (Maximum redundancy)", 2, 5, "Lose any 3 documents and still recover"),
    "custom": ("Custom", 0, 0, "Specify your own threshold and count"),
}


def prompt_passphrase_words() -> int:
    choices = {str(count): f"{count} words" for count in MNEMONIC_WORD_COUNTS}
    default = str(DEFAULT_PASSPHRASE_WORDS)
    value = prompt_choice(
        "Passphrase length",
        choices,
        default=default,
    )
    return int(value)


def _prompt_quorum_choice() -> ShardingConfig:
    """Single-choice quorum selection with presets."""
    choices = {key: desc for key, (desc, _, _, _) in QUORUM_PRESETS.items()}
    choice = prompt_choice(
        "Shard quorum",
        choices,
        default="2of3",
        help_text="How many shard documents are needed to recover the passphrase.",
    )

    if choice == "custom":
        threshold = prompt_int(
            "Required shards to recover",
            minimum=1,
            maximum=255,
            help_text="Minimum documents needed to reconstruct the passphrase.",
        )
        shares = prompt_int(
            "Total shard documents to create",
            minimum=threshold,
            maximum=255,
            help_text="Total documents created (must be >= required).",
        )
        return ShardingConfig(threshold=threshold, shares=shares)

    _, threshold, shares, _ = QUORUM_PRESETS[choice]
    return ShardingConfig(threshold=threshold, shares=shares)


def _prompt_quorum(
    *,
    label: str,
    default_threshold: int,
    default_shares: int,
    default_help_text: str,
    threshold_help_text: str,
    shares_help_text: str,
) -> ShardingConfig:
    choice = prompt_choice(
        f"{label} quorum",
        {
            "default": f"{default_threshold} of {default_shares} (Recommended)",
            "custom": "Custom",
        },
        default="default",
        help_text=default_help_text,
    )
    if choice == "default":
        return ShardingConfig(threshold=default_threshold, shares=default_shares)
    threshold = prompt_int(
        f"{label} threshold",
        minimum=1,
        maximum=255,
        help_text=threshold_help_text,
    )
    shares = prompt_int(
        f"{label} share count",
        minimum=threshold,
        maximum=255,
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
    args: BackupArgs | None,
) -> ShardingConfig | None:
    threshold = args.shard_threshold if args is not None else None
    shares = args.shard_count if args is not None else None

    # If values provided via CLI, validate and optionally confirm
    if threshold is not None or shares is not None:
        if threshold is None or shares is None:
            raise ValueError("both --shard-threshold and --shard-count are required")
        use_existing = prompt_yes_no(
            f"Use provided quorum ({threshold} of {shares})",
            default=True,
            help_text="Choose no to select a different quorum.",
        )
        if use_existing:
            return ShardingConfig(threshold=threshold, shares=shares)
        return _prompt_quorum_choice()

    # Interactive: single question about sharding
    sharding_choice = prompt_choice(
        "Passphrase sharding",
        {
            "shard": "Split into shard documents (Recommended)",
            "none": "No sharding (single passphrase)",
        },
        default="shard",
        help_text="Sharding distributes the passphrase across multiple documents for safety.",
    )
    if sharding_choice == "none":
        return None

    return _prompt_quorum_choice()


def resolve_signing_seed_mode(
    *,
    args: BackupArgs | None,
    sealed: bool,
    quiet: bool,
) -> SigningSeedMode:
    mode_arg = args.signing_key_mode if args is not None else None
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
            "Signing key storage",
            {
                "embedded": "In main document (Recommended - simpler recovery)",
                "sharded": "Separate shard documents (more secure)",
            },
            default="embedded",
            help_text="The signing key lets you create new shard documents later.",
        )
        signing_seed_mode = SigningSeedMode(signing_choice)
    return signing_seed_mode


def resolve_signing_seed_sharding(
    *,
    args: BackupArgs | None,
    signing_seed_mode: SigningSeedMode,
    passphrase_sharding: ShardingConfig,
) -> ShardingConfig | None:
    if signing_seed_mode != SigningSeedMode.SHARDED:
        return None

    sk_threshold = args.signing_key_shard_threshold if args is not None else None
    sk_count = args.signing_key_shard_count if args is not None else None

    # If values provided via CLI, validate and optionally confirm
    if sk_threshold is not None or sk_count is not None:
        if sk_threshold is None or sk_count is None:
            raise ValueError(
                "both --signing-key-shard-threshold and --signing-key-shard-count are required"
            )
        use_existing = prompt_yes_no(
            f"Use provided signing-key quorum ({sk_threshold} of {sk_count})",
            default=True,
            help_text="Choose no to select a different quorum.",
        )
        if use_existing:
            return ShardingConfig(threshold=sk_threshold, shares=sk_count)

    # Interactive: simple yes/no for using same quorum
    same_quorum = f"{passphrase_sharding.threshold} of {passphrase_sharding.shares}"
    use_same = prompt_yes_no(
        f"Use same quorum for signing-key shards ({same_quorum})",
        default=True,
        help_text="Choose no if you want different redundancy for signing keys.",
    )
    if use_same:
        return None

    return _prompt_quorum_choice()
