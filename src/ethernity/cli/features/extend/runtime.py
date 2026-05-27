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

from ethernity.cli.features.extend.root_shards import published_root_passphrase_shard_policy
from ethernity.cli.shared import api_codes
from ethernity.cli.shared.ndjson import ApiCommandError
from ethernity.cli.shared.recovery_kit_index import resolve_recovery_kit_index_template_path
from ethernity.cli.shared.types import ExtendArgs
from ethernity.config import BackupDefaults, apply_template_design, load_app_config
from ethernity.crypto.sharding import MAX_SHARES
from ethernity.crypto.signing import derive_public_key
from ethernity.render.layout_debug import (
    ensure_layout_debug_dir_allowed,
    ensure_layout_debug_dir_ready,
    resolve_layout_debug_dir,
)

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


def reject_reuse_root_passphrase_shard_overrides(args: ExtendArgs) -> None:
    conflicting_options: list[str] = []
    if args.shard_threshold is not None:
        conflicting_options.append("--shard-threshold")
    if args.shard_count is not None:
        conflicting_options.append("--shard-count")
    if conflicting_options:
        raise ApiCommandError(
            code=EXTENSION_INVALID_POLICY,
            message=(
                "unlock_policy=reuse-root cannot be combined with extension passphrase "
                "shard settings: " + ", ".join(conflicting_options)
            ),
        )


def resolve_extend_policy(
    *,
    args: ExtendArgs,
    defaults: BackupDefaults,
    root_passphrase_shard_threshold: int | None,
    root_passphrase_shard_count: int,
    require_recovery_kit_index: bool,
    inherited_passphrase_shard_threshold: int | None = None,
    inherited_passphrase_shard_count: int = 0,
) -> ResolvedExtendPolicy:
    unlock_policy = resolve_unlock_policy(args.unlock_policy)
    if unlock_policy == "reuse-root":
        reject_reuse_root_passphrase_shard_overrides(args)
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
            signing_key=resolve_extension_signing_key_policy(
                args=args,
                defaults=defaults,
                passphrase_recovery_available=True,
                inherit_default_mode=False,
            ),
        )

    if inherited_passphrase_shard_count <= 0 and root_passphrase_shard_count > 0:
        inherited_passphrase_shard_threshold = root_passphrase_shard_threshold
        inherited_passphrase_shard_count = root_passphrase_shard_count

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
        inherited_threshold=inherited_passphrase_shard_threshold,
        inherited_count=inherited_passphrase_shard_count,
    )

    signing_key_policy = resolve_extension_signing_key_policy(
        args=args,
        defaults=defaults,
        passphrase_recovery_available=passphrase_shard_count > 0,
        inherit_default_mode=True,
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


def resolve_extension_signing_key_policy(
    *,
    args: ExtendArgs,
    defaults: BackupDefaults,
    passphrase_recovery_available: bool,
    inherit_default_mode: bool,
) -> SigningKeyStoragePolicy:
    signing_key_mode = _resolve_extension_signing_key_mode(
        args,
        defaults,
        inherit_default_mode=inherit_default_mode,
    )
    if signing_key_mode == "not-stored":
        return SigningKeyNotStored()
    if not passphrase_recovery_available:
        raise ApiCommandError(
            code=EXTENSION_INVALID_POLICY,
            message="root/chain signing authority shard PDFs require passphrase shard recovery",
        )
    signing_key_shard_threshold, signing_key_shard_count = resolve_quorum_override(
        label="root/chain signing authority shards",
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
            message=(
                "signing-key-mode=sharded requires at least one root/chain signing "
                "authority shard PDF"
            ),
        )
    assert signing_key_shard_threshold is not None
    return ExtensionSigningKeyShards(
        threshold=signing_key_shard_threshold,
        share_count=signing_key_shard_count,
    )


def _resolve_extension_signing_key_mode(
    args: ExtendArgs,
    defaults: BackupDefaults,
    *,
    inherit_default_mode: bool,
) -> str:
    explicit_shard_policy = (
        args.signing_key_shard_threshold is not None or args.signing_key_shard_count is not None
    )
    if args.signing_key_mode is not None:
        if args.signing_key_mode not in {"not-stored", "sharded"}:
            raise ApiCommandError(
                code=EXTENSION_INVALID_POLICY,
                message="signing_key_mode must be 'not-stored' or 'sharded'",
                details={"signing_key_mode": args.signing_key_mode},
            )
        if args.signing_key_mode == "not-stored" and explicit_shard_policy:
            raise ApiCommandError(
                code=EXTENSION_INVALID_POLICY,
                message=(
                    "root/chain signing authority shard options require "
                    "signing_key_mode='sharded' or no explicit signing_key_mode"
                ),
            )
        return args.signing_key_mode
    if explicit_shard_policy:
        return "sharded"
    if inherit_default_mode and defaults.signing_key_mode == "sharded":
        return "sharded"
    return "not-stored"


def resolve_extend_runtime(
    prepared: PreparedExtendRun,
    *,
    create_layout_debug_dir: bool = True,
    include_layout_debug_dir: bool = True,
) -> ResolvedExtendRuntime:
    """Resolve config, validated unlock shard policy, and render settings."""

    config = apply_template_design(
        load_app_config(prepared.args.config, paper_size=prepared.args.paper),
        prepared.args.design,
    )
    sign_pub = derive_public_key(prepared.signing_seed)
    root_passphrase_shard_threshold, root_passphrase_shard_count = (
        resolve_root_passphrase_shard_policy(prepared, defaults=config.cli_defaults.backup)
    )
    inherited_passphrase_shard_threshold, inherited_passphrase_shard_count = (
        resolve_inherited_passphrase_shard_policy(
            prepared,
            root_passphrase_shard_threshold=root_passphrase_shard_threshold,
            root_passphrase_shard_count=root_passphrase_shard_count,
        )
    )
    kit_index_template_path = resolve_recovery_kit_index_template_path(config)
    require_recovery_kit_index = kit_index_template_path is not None
    policy = resolve_extend_policy(
        args=prepared.args,
        defaults=config.cli_defaults.backup,
        root_passphrase_shard_threshold=root_passphrase_shard_threshold,
        root_passphrase_shard_count=root_passphrase_shard_count,
        inherited_passphrase_shard_threshold=inherited_passphrase_shard_threshold,
        inherited_passphrase_shard_count=inherited_passphrase_shard_count,
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
        layout_debug_dir=(
            resolve_extend_layout_debug_dir(
                prepared.args.layout_debug_dir,
                root_dir=prepared.args.root_dir,
                create=create_layout_debug_dir,
            )
            if include_layout_debug_dir
            else None
        ),
        passphrase=policy.passphrase,
        signing_key=policy.signing_key,
        sign_pub=sign_pub,
        kit_index_template_path=kit_index_template_path,
    )


def resolve_root_passphrase_shard_policy(
    prepared: PreparedExtendRun,
    *,
    defaults: BackupDefaults,
) -> tuple[int | None, int]:
    threshold = prepared.root_passphrase_shard_threshold
    count = prepared.root_passphrase_shard_count
    if count > 0 or not _needs_published_root_passphrase_shard_policy(prepared.args, defaults):
        return threshold, count
    if (
        prepared.unlock_passphrase_shard_count > 0
        and resolve_unlock_policy(prepared.args.unlock_policy) != "reuse-root"
    ):
        return threshold, count

    root_dir = prepared.args.root_dir
    root_doc_id = prepared.inspection.root_doc_id
    if not root_dir or root_doc_id is None:
        return threshold, count

    try:
        return published_root_passphrase_shard_policy(
            Path(root_dir).expanduser().resolve(),
            root_doc_id=bytes.fromhex(root_doc_id),
            root_doc_hash=prepared.root_doc_hash,
            sign_pub=derive_public_key(prepared.signing_seed),
            quiet=prepared.args.quiet,
        )
    except ValueError as exc:
        raise ApiCommandError(
            code=api_codes.ROOT_SHARD_POLICY_INVALID,
            message=str(exc),
            details={"stage": "shards"},
        ) from exc


def resolve_inherited_passphrase_shard_policy(
    prepared: PreparedExtendRun,
    *,
    root_passphrase_shard_threshold: int | None,
    root_passphrase_shard_count: int,
) -> tuple[int | None, int]:
    if prepared.unlock_passphrase_shard_count > 0:
        return (
            prepared.unlock_passphrase_shard_threshold,
            prepared.unlock_passphrase_shard_count,
        )
    return root_passphrase_shard_threshold, root_passphrase_shard_count


def _needs_published_root_passphrase_shard_policy(
    args: ExtendArgs,
    defaults: BackupDefaults,
) -> bool:
    unlock_policy = resolve_unlock_policy(args.unlock_policy)
    if unlock_policy == "reuse-root":
        return True
    if args.shard_count is not None:
        return False
    return defaults.shard_count is None


def resolve_extend_layout_debug_dir(
    path: str | None,
    *,
    root_dir: str | None,
    create: bool = True,
) -> str | None:
    if path is None or not path.strip():
        return None
    debug_dir = Path(path).expanduser().resolve()
    ensure_extend_layout_debug_dir_allowed(debug_dir, root_dir=root_dir)
    if not create:
        try:
            ensure_layout_debug_dir_ready(debug_dir)
        except ValueError as exc:
            raise ApiCommandError(
                code=EXTENSION_INVALID_POLICY,
                message=f"--layout-debug-dir is not usable: {exc}",
                details={"layout_debug_dir": str(debug_dir)},
            ) from exc
        return str(debug_dir)
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
    if count > MAX_SHARES or threshold is not None and threshold > MAX_SHARES:
        raise ApiCommandError(
            code=EXTENSION_INVALID_POLICY,
            message=f"{label} threshold and shard count must be <= {MAX_SHARES}",
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
