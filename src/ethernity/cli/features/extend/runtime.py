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

"""Runtime and publish-policy helpers for extend execution."""

from __future__ import annotations

from pathlib import Path

from ethernity.cli.features.backup import execution as backup_execution
from ethernity.cli.shared.ndjson import ApiCommandError
from ethernity.cli.shared.types import ExtendArgs
from ethernity.config import BackupDefaults, apply_template_design, load_app_config
from ethernity.crypto.signing import derive_public_key
from ethernity.render.layout_debug import ensure_layout_debug_dir_allowed, resolve_layout_debug_dir

from .models import (
    EXTENSION_INVALID_POLICY,
    ExtensionPassphraseShards,
    ExtensionSigningKeyShards,
    PassphraseStoragePolicy,
    PlaintextPassphrase,
    PreparedExtendRun,
    ResolvedExtendPolicy,
    ResolvedExtendRuntime,
    ReuseRootPassphraseShards,
    SigningKeyNotStored,
    SigningKeyStoragePolicy,
)


def resolve_unlock_policy(policy: str | None) -> str:
    if policy is None:
        return "self-contained"
    if policy not in {"self-contained", "reuse-root"}:
        raise ApiCommandError(
            code=EXTENSION_INVALID_POLICY,
            message="unlock_policy must be 'self-contained' or 'reuse-root'",
        )
    return policy


def reject_reuse_root_shard_overrides(args: ExtendArgs) -> None:
    conflicting_options: list[str] = []
    if args.shard_threshold is not None:
        conflicting_options.append("--shard-threshold")
    if args.shard_count is not None:
        conflicting_options.append("--shard-count")
    if args.signing_key_mode is not None:
        conflicting_options.append("--signing-key-mode")
    if args.signing_key_shard_threshold is not None:
        conflicting_options.append("--signing-key-shard-threshold")
    if args.signing_key_shard_count is not None:
        conflicting_options.append("--signing-key-shard-count")
    if conflicting_options:
        raise ApiCommandError(
            code=EXTENSION_INVALID_POLICY,
            message=(
                "unlock_policy=reuse-root cannot be combined with explicit shard settings: "
                + ", ".join(conflicting_options)
            ),
        )


def resolve_extend_policy(
    *,
    args: ExtendArgs,
    defaults: BackupDefaults,
    root_passphrase_shard_threshold: int | None,
    root_passphrase_shard_count: int,
    require_recovery_kit_index: bool,
) -> ResolvedExtendPolicy:
    unlock_policy = resolve_unlock_policy(args.unlock_policy)
    if unlock_policy == "reuse-root":
        reject_reuse_root_shard_overrides(args)
        if root_passphrase_shard_threshold is None or root_passphrase_shard_count <= 0:
            raise ApiCommandError(
                code=EXTENSION_INVALID_POLICY,
                message=(
                    "unlock_policy=reuse-root requires a published or supplied root "
                    "passphrase shard policy"
                ),
            )
        return ResolvedExtendPolicy(
            require_recovery_kit_index=require_recovery_kit_index,
            passphrase=ReuseRootPassphraseShards(
                threshold=root_passphrase_shard_threshold,
                share_count=root_passphrase_shard_count,
            ),
            signing_key=SigningKeyNotStored(),
        )

    requested_passphrase_threshold = (
        args.shard_threshold
        if args.shard_threshold is not None
        else (0 if args.shard_count == 0 else defaults.shard_threshold)
    )
    requested_passphrase_count = (
        args.shard_count if args.shard_count is not None else defaults.shard_count
    )
    passphrase_shard_threshold, passphrase_shard_count = resolve_quorum_override(
        label="passphrase shards",
        requested_threshold=requested_passphrase_threshold,
        requested_count=requested_passphrase_count,
        inherited_threshold=root_passphrase_shard_threshold,
        inherited_count=root_passphrase_shard_count,
    )

    signing_key_mode = args.signing_key_mode or defaults.signing_key_mode or "embedded"
    signing_key_policy: SigningKeyStoragePolicy
    if signing_key_mode == "embedded":
        signing_key_policy = SigningKeyNotStored()
    else:
        if passphrase_shard_count <= 0:
            raise ApiCommandError(
                code=EXTENSION_INVALID_POLICY,
                message="signing-key shard PDFs require passphrase shard PDFs",
            )
        signing_key_shard_threshold, signing_key_shard_count = resolve_quorum_override(
            label="signing-key shards",
            requested_threshold=(
                args.signing_key_shard_threshold
                if args.signing_key_shard_threshold is not None
                else defaults.signing_key_shard_threshold
            ),
            requested_count=(
                args.signing_key_shard_count
                if args.signing_key_shard_count is not None
                else defaults.signing_key_shard_count
            ),
            inherited_threshold=None,
            inherited_count=0,
        )
        if signing_key_shard_count <= 0:
            raise ApiCommandError(
                code=EXTENSION_INVALID_POLICY,
                message="signing-key-mode=sharded requires at least one signing-key shard PDF",
            )
        assert signing_key_shard_threshold is not None
        signing_key_policy = ExtensionSigningKeyShards(
            threshold=signing_key_shard_threshold,
            share_count=signing_key_shard_count,
        )

    passphrase_policy: PassphraseStoragePolicy
    if passphrase_shard_count > 0:
        assert passphrase_shard_threshold is not None
        passphrase_policy = ExtensionPassphraseShards(
            threshold=passphrase_shard_threshold,
            share_count=passphrase_shard_count,
        )
    else:
        if args.shard_count != 0:
            raise ApiCommandError(
                code=EXTENSION_INVALID_POLICY,
                message=(
                    "extend would write a recovery document containing the plaintext "
                    "passphrase. Configure extension passphrase shards with --shard-count "
                    "and --shard-threshold, use --unlock-policy reuse-root with root shards, "
                    "or pass --shard-count 0 to explicitly choose plaintext passphrase output."
                ),
            )
        passphrase_policy = PlaintextPassphrase()

    return ResolvedExtendPolicy(
        require_recovery_kit_index=require_recovery_kit_index,
        passphrase=passphrase_policy,
        signing_key=signing_key_policy,
    )


def resolve_extend_runtime(
    prepared: PreparedExtendRun,
) -> ResolvedExtendRuntime:
    """Resolve config, validated unlock shard policy, and render settings."""

    config = apply_template_design(
        load_app_config(prepared.args.config, paper_size=prepared.args.paper),
        prepared.args.design,
    )
    sign_pub = derive_public_key(prepared.signing_seed)
    kit_index_template_path = backup_execution._resolve_kit_index_template_path(config)
    require_recovery_kit_index = kit_index_template_path is not None
    policy = resolve_extend_policy(
        args=prepared.args,
        defaults=config.cli_defaults.backup,
        root_passphrase_shard_threshold=prepared.root_passphrase_shard_threshold,
        root_passphrase_shard_count=prepared.root_passphrase_shard_count,
        require_recovery_kit_index=require_recovery_kit_index,
    )

    qr_chunk_size = resolve_qr_chunk_size(
        requested=prepared.args.qr_chunk_size,
        default=config.qr_chunk_size,
    )

    return ResolvedExtendRuntime(
        config=config,
        qr_chunk_size=qr_chunk_size,
        qr_payload_codec=config.cli_defaults.backup.qr_payload_codec,
        layout_debug_dir=resolve_extend_layout_debug_dir(
            prepared.args.layout_debug_dir,
            root_dir=prepared.args.root_dir,
        ),
        passphrase=policy.passphrase,
        signing_key=policy.signing_key,
        sign_pub=sign_pub,
        kit_index_template_path=kit_index_template_path,
    )


def resolve_extend_layout_debug_dir(path: str | None, *, root_dir: str | None) -> str | None:
    if path is None or not path.strip():
        return None
    debug_dir = Path(path).expanduser().resolve()
    ensure_extend_layout_debug_dir_allowed(debug_dir, root_dir=root_dir)
    return resolve_layout_debug_dir(str(debug_dir))


def ensure_extend_layout_debug_dir_allowed(path: str | Path, *, root_dir: str | None) -> None:
    debug_dir = Path(path).expanduser().resolve()
    if root_dir:
        extensions_dir = Path(root_dir).expanduser().resolve() / "extensions"
        try:
            ensure_layout_debug_dir_allowed(
                debug_dir,
                forbidden_dirs={"extensions directory": extensions_dir},
            )
        except ValueError as exc:
            raise ApiCommandError(
                code=EXTENSION_INVALID_POLICY,
                message=(
                    "--layout-debug-dir must not be inside the backup root extensions "
                    "directory; choose a separate diagnostics directory"
                ),
                details={"layout_debug_dir": str(debug_dir), "extensions_dir": str(extensions_dir)},
            ) from exc


def resolve_quorum_override(
    *,
    label: str,
    requested_threshold: int | None,
    requested_count: int | None,
    inherited_threshold: int | None,
    inherited_count: int,
) -> tuple[int | None, int]:
    count = inherited_count if requested_count is None else requested_count
    threshold = inherited_threshold if requested_threshold is None else requested_threshold

    if count < 0 or threshold is not None and threshold < 0:
        raise ApiCommandError(
            code=EXTENSION_INVALID_POLICY,
            message=f"{label} must use non-negative integer settings",
        )
    if count == 0:
        if threshold not in {None, 0}:
            raise ApiCommandError(
                code=EXTENSION_INVALID_POLICY,
                message=f"{label} threshold cannot be set when shard count is 0",
            )
        return None, 0
    if threshold is None:
        raise ApiCommandError(
            code=EXTENSION_INVALID_POLICY,
            message=f"{label} threshold must be provided when shard count is non-zero",
        )
    if threshold <= 0 or threshold > count:
        raise ApiCommandError(
            code=EXTENSION_INVALID_POLICY,
            message=f"{label} threshold must be between 1 and the shard count",
        )
    return threshold, count


def resolve_qr_chunk_size(requested: int | None, default: int) -> int:
    qr_chunk_size = default if requested is None else requested
    if qr_chunk_size <= 0:
        raise ApiCommandError(
            code=EXTENSION_INVALID_POLICY,
            message="extend qr_chunk_size must be a positive integer",
        )
    return qr_chunk_size
