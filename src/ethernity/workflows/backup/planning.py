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

from ethernity.core.models import DocumentPlan, ShardingConfig, SigningSeedMode
from ethernity.workflows.shared.requests import BackupRequest


def build_document_plan(
    *,
    sealed: bool,
    sharding: ShardingConfig | None,
    signing_seed_mode: SigningSeedMode,
    signing_seed_sharding: ShardingConfig | None,
) -> DocumentPlan:
    return DocumentPlan(
        sealed=sealed,
        signing_seed_mode=signing_seed_mode,
        sharding=sharding,
        signing_seed_sharding=signing_seed_sharding,
    )


def plan_from_request(args: BackupRequest) -> DocumentPlan:
    sharding = _sharding_from_args(args)
    signing_seed_mode = _signing_seed_mode_from_args(args)
    signing_seed_sharding = _signing_seed_sharding_from_args(
        args,
        signing_seed_mode=signing_seed_mode,
        sharding=sharding,
    )
    return build_document_plan(
        sealed=args.sealed,
        sharding=sharding,
        signing_seed_mode=signing_seed_mode,
        signing_seed_sharding=signing_seed_sharding,
    )


def _sharding_from_args(args: BackupRequest) -> ShardingConfig | None:
    if args.shard_threshold or args.shard_count:
        if not args.shard_threshold or not args.shard_count:
            raise ValueError("both --shard-threshold and --shard-count are required")
        return ShardingConfig(threshold=args.shard_threshold, shares=args.shard_count)
    return None


def _signing_seed_mode_from_args(args: BackupRequest) -> SigningSeedMode:
    if args.signing_key_mode:
        return SigningSeedMode(args.signing_key_mode)
    return SigningSeedMode.EMBEDDED


def _signing_seed_sharding_from_args(
    args: BackupRequest,
    *,
    signing_seed_mode: SigningSeedMode,
    sharding: ShardingConfig | None,
) -> ShardingConfig | None:
    if signing_seed_mode != SigningSeedMode.SHARDED:
        return None
    if sharding is None:
        raise ValueError("signing key sharding requires passphrase sharding")
    if args.signing_key_shard_threshold is None or args.signing_key_shard_count is None:
        return None
    return ShardingConfig(
        threshold=args.signing_key_shard_threshold,
        shares=args.signing_key_shard_count,
    )
