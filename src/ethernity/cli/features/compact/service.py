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

from pathlib import Path

from ethernity.cli.features.backup.execution import run_backup
from ethernity.cli.features.backup.planning import plan_from_args as plan_backup_from_args
from ethernity.cli.features.backup.service import apply_qr_chunk_size_override
from ethernity.cli.features.extend.runtime import infer_root_publish_policy
from ethernity.cli.features.recover.chain import (
    recover_chain_entries,
    validated_root_recovery_scan_paths,
)
from ethernity.cli.features.recover.planning import plan_from_args as plan_recover_from_args
from ethernity.cli.shared.types import BackupArgs, BackupResult, CompactArgs, InputFile, RecoverArgs
from ethernity.config import apply_template_design, load_app_config
from ethernity.crypto.signing import derive_public_key
from ethernity.render.types import RenderLineage

_infer_root_publish_policy = infer_root_publish_policy


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
    if not validated_root_recovery_scan_paths(root_dir):
        raise ValueError(
            "backup root folder (backup root directory) does not contain a root MAIN carrier "
            f"(qr_document.pdf or recovery_document.pdf): {root_dir_value}"
        )
    return root_dir


def run_compact(args: CompactArgs) -> BackupResult:
    root_dir = _validated_compact_root_dir(args.root_dir)
    if not args.output_dir:
        raise ValueError("compact requires output_dir")

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
    chain = recover_chain_entries(recover_plan, quiet=args.quiet, debug=False)
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
