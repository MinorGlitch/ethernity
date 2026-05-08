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
from ethernity.cli.features.recover.key_recovery import (
    InsufficientShardError,
    _validated_shard_payloads_from_frames,
)
from ethernity.cli.shared.io.frames import _shard_frames_from_scan
from ethernity.cli.shared.ndjson import ApiCommandError
from ethernity.cli.shared.types import ExtendArgs
from ethernity.config import BackupDefaults, apply_template_design, load_app_config
from ethernity.crypto import sharding as sharding_module
from ethernity.crypto.signing import derive_public_key

from .models import (
    EXTENSION_INVALID_POLICY,
    ExtensionPassphraseShards,
    ExtensionSigningKeyShards,
    InheritedRootPublishPolicy,
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
    inherited: InheritedRootPublishPolicy,
    require_recovery_kit_index: bool,
) -> ResolvedExtendPolicy:
    unlock_policy = resolve_unlock_policy(args.unlock_policy)
    if unlock_policy == "reuse-root":
        reject_reuse_root_shard_overrides(args)
        if inherited.passphrase_shard_threshold is None or inherited.passphrase_shard_count <= 0:
            raise ApiCommandError(
                code=EXTENSION_INVALID_POLICY,
                message=(
                    "unlock_policy=reuse-root requires passphrase shard PDFs on the root backup"
                ),
            )
        return ResolvedExtendPolicy(
            require_recovery_kit_index=require_recovery_kit_index,
            passphrase=ReuseRootPassphraseShards(
                threshold=inherited.passphrase_shard_threshold,
                share_count=inherited.passphrase_shard_count,
            ),
            signing_key=SigningKeyNotStored(),
        )

    passphrase_shard_threshold, passphrase_shard_count = resolve_quorum_override(
        label="passphrase shards",
        requested_threshold=(
            args.shard_threshold if args.shard_threshold is not None else defaults.shard_threshold
        ),
        requested_count=args.shard_count if args.shard_count is not None else defaults.shard_count,
        inherited_threshold=inherited.passphrase_shard_threshold,
        inherited_count=inherited.passphrase_shard_count,
    )

    signing_key_mode = (
        args.signing_key_mode
        or defaults.signing_key_mode
        or ("sharded" if inherited.signing_key_shard_count else "embedded")
    )
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
            inherited_threshold=inherited.signing_key_shard_threshold,
            inherited_count=inherited.signing_key_shard_count,
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
        passphrase_policy = PlaintextPassphrase()

    return ResolvedExtendPolicy(
        require_recovery_kit_index=require_recovery_kit_index,
        passphrase=passphrase_policy,
        signing_key=signing_key_policy,
    )


def resolve_extend_runtime(
    prepared: PreparedExtendRun,
) -> ResolvedExtendRuntime:
    """Resolve config, inherited publish policy, and render settings for an extension."""

    config = apply_template_design(
        load_app_config(prepared.args.config, paper_size=prepared.args.paper),
        prepared.args.design,
    )
    sign_pub = derive_public_key(prepared.signing_seed)
    unlock_policy = resolve_unlock_policy(prepared.args.unlock_policy)
    inherited = infer_root_publish_policy(
        root_dir=prepared.args.root_dir,
        root_doc_id_hex=prepared.inspection.root_doc_id,
        root_doc_hash=prepared.root_doc_hash,
        sign_pub=sign_pub,
        quiet=prepared.args.quiet,
        require_quorum=unlock_policy == "reuse-root",
    )
    kit_index_template_path = backup_execution._resolve_kit_index_template_path(config)
    require_recovery_kit_index = kit_index_template_path is not None
    policy = resolve_extend_policy(
        args=prepared.args,
        defaults=config.cli_defaults.backup,
        inherited=inherited,
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
        layout_debug_dir=backup_execution._resolve_layout_debug_dir(prepared.args.layout_debug_dir),
        passphrase=policy.passphrase,
        signing_key=policy.signing_key,
        sign_pub=sign_pub,
        kit_index_template_path=kit_index_template_path,
    )


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


def infer_root_publish_policy(
    *,
    root_dir: str | None,
    root_doc_id_hex: str | None,
    root_doc_hash: bytes,
    sign_pub: bytes | None,
    allow_unsigned: bool = False,
    require_quorum: bool = True,
    quiet: bool,
) -> InheritedRootPublishPolicy:
    if not root_dir:
        raise ApiCommandError(
            code="RUNTIME_ERROR",
            message="extend execution requires a root_dir for publish-policy inheritance",
        )

    root_path = Path(root_dir).expanduser()
    if root_path.is_symlink():
        raise ApiCommandError(
            code="RUNTIME_ERROR",
            message="root backup directory must not be a symlink",
        )
    if root_path.exists() and not root_path.is_dir():
        raise ApiCommandError(
            code="RUNTIME_ERROR",
            message=f"root backup directory must be a directory: {root_dir}",
        )
    root_doc_id = bytes.fromhex(root_doc_id_hex) if root_doc_id_hex else None
    passphrase_threshold, passphrase_count = infer_root_quorum(
        sorted(root_path.glob("shard-*.pdf")),
        expected_doc_id=root_doc_id,
        expected_doc_hash=root_doc_hash,
        sign_pub=sign_pub,
        allow_unsigned=allow_unsigned,
        require_quorum=require_quorum,
        quiet=quiet,
        key_type=sharding_module.KEY_TYPE_PASSPHRASE,
        secret_label="passphrase",
    )
    signing_key_threshold, signing_key_count = infer_root_quorum(
        sorted(root_path.glob("signing-key-shard-*.pdf")),
        expected_doc_id=root_doc_id,
        expected_doc_hash=root_doc_hash,
        sign_pub=sign_pub,
        allow_unsigned=allow_unsigned,
        require_quorum=require_quorum,
        quiet=quiet,
        key_type=sharding_module.KEY_TYPE_SIGNING_SEED,
        secret_label="signing key",
    )
    return InheritedRootPublishPolicy(
        passphrase_shard_threshold=passphrase_threshold,
        passphrase_shard_count=passphrase_count,
        signing_key_shard_threshold=signing_key_threshold,
        signing_key_shard_count=signing_key_count,
    )


def infer_root_quorum(
    paths: list[Path],
    *,
    expected_doc_id: bytes | None,
    expected_doc_hash: bytes,
    sign_pub: bytes | None,
    allow_unsigned: bool,
    require_quorum: bool = True,
    quiet: bool,
    key_type: str,
    secret_label: str,
) -> tuple[int | None, int]:
    if not paths:
        return None, 0
    frames = _shard_frames_from_scan([str(path) for path in paths], quiet=quiet)
    try:
        shares = _validated_shard_payloads_from_frames(
            frames,
            expected_doc_id=expected_doc_id,
            expected_doc_hash=expected_doc_hash,
            expected_sign_pub=sign_pub,
            allow_unsigned=allow_unsigned,
            key_type=key_type,
            secret_label=secret_label,
        )
    except InsufficientShardError as exc:
        if not require_quorum and exc.share_count is not None:
            return exc.threshold, exc.share_count
        raise ApiCommandError(
            code=EXTENSION_INVALID_POLICY,
            message=(
                f"root {secret_label} shards are under quorum; "
                f"need at least {exc.threshold}, found {exc.provided_count}"
            ),
        ) from exc
    first = shares[0]
    return first.threshold, first.share_count
