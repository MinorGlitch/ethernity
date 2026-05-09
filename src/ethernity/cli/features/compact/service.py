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

"""Latest-state compaction helpers for root-plus-extension chains."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ethernity.cli.features.backup.execution import run_backup
from ethernity.cli.features.backup.planning import plan_from_args as plan_backup_from_args
from ethernity.cli.features.backup.service import apply_qr_chunk_size_override
from ethernity.cli.features.recover.chain import recover_chain_entries
from ethernity.cli.features.recover.key_recovery import (
    InsufficientShardError,
    _validated_shard_payloads_from_frames,
)
from ethernity.cli.features.recover.planning import plan_from_args as plan_recover_from_args
from ethernity.cli.shared import api_codes
from ethernity.cli.shared.io.frames import _shard_frames_from_scan
from ethernity.cli.shared.ndjson import ApiCommandError
from ethernity.cli.shared.types import BackupArgs, BackupResult, CompactArgs, InputFile, RecoverArgs
from ethernity.config import apply_template_design, load_app_config
from ethernity.crypto import sharding as sharding_module
from ethernity.crypto.signing import derive_public_key
from ethernity.encoding.framing import Frame
from ethernity.render.types import RenderLineage


@dataclass(frozen=True)
class _RootPublishPolicy:
    passphrase_shard_threshold: int | None
    passphrase_shard_count: int
    signing_key_shard_threshold: int | None
    signing_key_shard_count: int


def _validated_compact_root_dir(root_dir_value: str | None) -> Path:
    if not root_dir_value:
        raise ValueError("compact requires root_dir")
    root_dir = Path(root_dir_value).expanduser()
    if root_dir.is_symlink():
        raise ValueError(
            f"backup root folder (backup root directory) must not be a symlink: {root_dir_value}"
        )
    if not root_dir.exists():
        raise ValueError(
            "backup root folder (backup root directory) not found: "
            f"{root_dir_value}. Check --root-dir and try again."
        )
    if not root_dir.is_dir():
        raise ValueError(f"--root-dir must be a directory: {root_dir_value}")
    return root_dir


def _reject_compact_output_inside_root(root_dir: Path, output_dir_value: str) -> None:
    output_dir = Path(output_dir_value).expanduser()
    root_resolved = root_dir.resolve(strict=False)
    output_resolved = output_dir.resolve(strict=False)
    if output_resolved == root_resolved or output_resolved.is_relative_to(root_resolved):
        raise ValueError(
            "compact output directory must not be the source backup root or inside it: "
            f"{output_dir_value}"
        )


def _translate_compact_head_untrusted(exc: ApiCommandError) -> ApiCommandError:
    head_label = "requested" if exc.details.get("explicit_selection") else "latest supplied"
    message = f"{head_label} compact head could not be trusted; no checkpoint was created"
    failure_message = exc.details.get("failure_message")
    if isinstance(failure_message, str) and failure_message:
        message = f"{message}: {failure_message}"
    details = dict(exc.details)
    details["checkpoint_created"] = False
    return ApiCommandError(code=exc.code, message=message, details=details)


def _infer_root_publish_policy(
    *,
    root_dir: str | None,
    root_doc_id_hex: str | None,
    root_doc_hash: bytes,
    sign_pub: bytes | None,
    passphrase_shard_frames: Sequence[Frame] = (),
    signing_key_shard_frames: Sequence[Frame] = (),
    allow_unsigned: bool = False,
    require_quorum: bool = True,
    quiet: bool,
) -> _RootPublishPolicy:
    if not root_dir:
        raise ApiCommandError(
            code="RUNTIME_ERROR",
            message="compact execution requires a root_dir for publish-policy inheritance",
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
    passphrase_threshold, passphrase_count = _infer_root_quorum(
        sorted(root_path.glob("shard-*.pdf")),
        extra_frames=passphrase_shard_frames,
        expected_doc_id=root_doc_id,
        expected_doc_hash=root_doc_hash,
        sign_pub=sign_pub,
        allow_unsigned=allow_unsigned,
        require_quorum=require_quorum,
        quiet=quiet,
        key_type=sharding_module.KEY_TYPE_PASSPHRASE,
        secret_label="passphrase",
    )
    signing_key_threshold, signing_key_count = _infer_root_quorum(
        sorted(root_path.glob("signing-key-shard-*.pdf")),
        extra_frames=signing_key_shard_frames,
        expected_doc_id=root_doc_id,
        expected_doc_hash=root_doc_hash,
        sign_pub=sign_pub,
        allow_unsigned=allow_unsigned,
        require_quorum=require_quorum,
        quiet=quiet,
        key_type=sharding_module.KEY_TYPE_SIGNING_SEED,
        secret_label="signing key",
    )
    return _RootPublishPolicy(
        passphrase_shard_threshold=passphrase_threshold,
        passphrase_shard_count=passphrase_count,
        signing_key_shard_threshold=signing_key_threshold,
        signing_key_shard_count=signing_key_count,
    )


def _infer_root_quorum(
    paths: list[Path],
    *,
    extra_frames: Sequence[Frame] = (),
    expected_doc_id: bytes | None,
    expected_doc_hash: bytes,
    sign_pub: bytes | None,
    allow_unsigned: bool,
    require_quorum: bool = True,
    quiet: bool,
    key_type: str,
    secret_label: str,
) -> tuple[int | None, int]:
    frames = list(extra_frames)
    if paths:
        frames.extend(_shard_frames_from_scan([str(path) for path in paths], quiet=quiet))
    if not frames:
        return None, 0
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
            code=api_codes.COMPACT_INVALID_POLICY,
            message=(
                f"root {secret_label} shards are under quorum; "
                f"need at least {exc.threshold}, found {exc.provided_count}"
            ),
        ) from exc
    first = shares[0]
    return first.threshold, first.share_count


def run_compact(args: CompactArgs) -> BackupResult:
    root_dir = _validated_compact_root_dir(args.root_dir)
    if not args.output_dir:
        raise ValueError("compact requires output_dir")
    _reject_compact_output_inside_root(root_dir, args.output_dir)

    recover_plan = plan_recover_from_args(
        RecoverArgs(
            scan=[str(root_dir)],
            passphrase=args.passphrase,
            shard_fallback_file=args.shard_fallback_file,
            shard_payloads_file=args.shard_payloads_file,
            shard_scan=args.shard_scan,
            shard_frames=args.shard_frames,
            auth_fallback_file=args.auth_fallback_file,
            auth_payloads_file=args.auth_payloads_file,
            auth_frames=args.auth_frames,
            allow_unsigned=False,
            quiet=args.quiet,
        )
    )
    try:
        chain = recover_chain_entries(recover_plan, quiet=args.quiet, debug=False)
    except ApiCommandError as exc:
        if exc.code != api_codes.RECOVERY_HEAD_UNTRUSTED:
            raise
        raise _translate_compact_head_untrusted(exc) from exc
    manifest = chain.manifest

    sign_pub = (
        derive_public_key(manifest.signing_seed)
        if manifest.signing_seed is not None
        else (recover_plan.auth_payload.sign_pub if recover_plan.auth_payload is not None else None)
    )

    inherited = _infer_root_publish_policy(
        root_dir=str(root_dir),
        root_doc_id_hex=recover_plan.doc_id.hex(),
        root_doc_hash=recover_plan.doc_hash,
        sign_pub=sign_pub,
        passphrase_shard_frames=recover_plan.shard_frames,
        allow_unsigned=sign_pub is None,
        quiet=args.quiet,
    )
    if (
        not manifest.sealed
        and inherited.signing_key_shard_count > 0
        and (inherited.passphrase_shard_count <= 0 or inherited.passphrase_shard_threshold is None)
    ):
        raise ValueError(
            "root backup signing-key shards require passphrase shards; "
            "compact cannot preserve an invalid shard policy"
        )
    backup_args = BackupArgs(
        config=args.config,
        paper=args.paper,
        design=args.design,
        output_dir=args.output_dir,
        output_dir_existing_parent=True,
        layout_debug_dir=args.layout_debug_dir,
        qr_chunk_size=args.qr_chunk_size,
        passphrase=recover_plan.passphrase,
        sealed=manifest.sealed,
        shard_threshold=inherited.passphrase_shard_threshold,
        shard_count=inherited.passphrase_shard_count or None,
        signing_key_mode=(
            "sharded"
            if not manifest.sealed and inherited.signing_key_shard_count > 0
            else "embedded"
        ),
        signing_key_shard_threshold=(
            inherited.signing_key_shard_threshold if not manifest.sealed else None
        ),
        signing_key_shard_count=inherited.signing_key_shard_count if not manifest.sealed else None,
        quiet=args.quiet,
    )
    config = load_app_config(backup_args.config, paper_size=backup_args.paper)
    config = apply_template_design(config, backup_args.design)
    config = apply_qr_chunk_size_override(config, backup_args.qr_chunk_size)
    backup_plan = plan_backup_from_args(backup_args)
    input_files = [
        InputFile(
            source_path=None,
            relative_path=entry.path,
            data=data,
            mtime=entry.mtime,
        )
        for entry, data in chain.extracted
    ]
    return run_backup(
        input_files=input_files,
        base_dir=None,
        output_dir=backup_args.output_dir,
        output_dir_existing_parent=backup_args.output_dir_existing_parent,
        layout_debug_dir=backup_args.layout_debug_dir,
        input_origin=manifest.input_origin,
        input_roots=list(manifest.input_roots),
        plan=backup_plan,
        passphrase=backup_args.passphrase,
        config=config,
        signing_seed_override=None if manifest.sealed else manifest.signing_seed,
        render_lineage=RenderLineage(kind="compaction_checkpoint"),
        quiet=args.quiet,
    )
