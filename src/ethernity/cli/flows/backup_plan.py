#!/usr/bin/env python3
from __future__ import annotations

import argparse

from ...core.models import DocumentPlan, ShardingConfig, SigningSeedMode


def build_document_plan(
    *,
    sealed: bool,
    sharding: ShardingConfig | None,
    signing_seed_mode: SigningSeedMode,
    signing_seed_sharding: ShardingConfig | None,
) -> DocumentPlan:
    return DocumentPlan(
        version=1,
        sealed=sealed,
        signing_seed_mode=signing_seed_mode,
        sharding=sharding,
        signing_seed_sharding=signing_seed_sharding,
    )


def plan_from_args(args: argparse.Namespace) -> DocumentPlan:
    sharding = _sharding_from_args(args)
    signing_seed_mode = _signing_seed_mode_from_args(args)
    signing_seed_sharding = _signing_seed_sharding_from_args(
        args,
        signing_seed_mode=signing_seed_mode,
        sharding=sharding,
    )
    return build_document_plan(
        sealed=bool(args.sealed),
        sharding=sharding,
        signing_seed_mode=signing_seed_mode,
        signing_seed_sharding=signing_seed_sharding,
    )


def _sharding_from_args(args: argparse.Namespace) -> ShardingConfig | None:
    if args.shard_threshold or args.shard_count:
        if not args.shard_threshold or not args.shard_count:
            raise ValueError("both --shard-threshold and --shard-count are required")
        return ShardingConfig(threshold=args.shard_threshold, shares=args.shard_count)
    return None


def _signing_seed_mode_from_args(args: argparse.Namespace) -> SigningSeedMode:
    signing_key_mode = getattr(args, "signing_key_mode", None)
    return SigningSeedMode(signing_key_mode) if signing_key_mode else SigningSeedMode.EMBEDDED


def _signing_seed_sharding_from_args(
    args: argparse.Namespace,
    *,
    signing_seed_mode: SigningSeedMode,
    sharding: ShardingConfig | None,
) -> ShardingConfig | None:
    if signing_seed_mode != SigningSeedMode.SHARDED:
        return None
    if sharding is None:
        raise ValueError("signing key sharding requires passphrase sharding")
    signing_key_shard_threshold = getattr(args, "signing_key_shard_threshold", None)
    signing_key_shard_count = getattr(args, "signing_key_shard_count", None)
    if signing_key_shard_threshold is None or signing_key_shard_count is None:
        return None
    return ShardingConfig(
        threshold=signing_key_shard_threshold,
        shares=signing_key_shard_count,
    )
