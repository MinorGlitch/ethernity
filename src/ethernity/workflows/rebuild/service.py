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

"""Rebuild the latest state of root-plus-extension chains."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from ethernity.config import apply_render_style, load_app_config
from ethernity.crypto import sharding as sharding_module
from ethernity.crypto.document_identity import doc_id_from_doc_hash
from ethernity.crypto.signing import derive_public_key
from ethernity.encoding.framing import Frame, FrameType
from ethernity.extensions.errors import ExtensionRecoveryError
from ethernity.extensions.recovery import recover_chain_entries
from ethernity.render.types import DocumentOrigin
from ethernity.workflows.backup.execution import run_backup
from ethernity.workflows.backup.planning import plan_from_request as plan_backup_request
from ethernity.workflows.backup.service import apply_qr_chunk_size_override
from ethernity.workflows.recovery.frame_inputs import frames_from_scan
from ethernity.workflows.recovery.keys import (
    InsufficientShardError,
    validated_shard_payloads_from_frames,
)
from ethernity.workflows.recovery.planning import plan_from_request as plan_recovery_request
from ethernity.workflows.recovery.root_shard_policy import (
    decoded_shard_candidates,
    has_potential_root_shard_frames,
    root_shard_quorum_from_frames,
)
from ethernity.workflows.shared import issue_codes
from ethernity.workflows.shared.events import CommandError as ApiCommandError, emit_phase
from ethernity.workflows.shared.operation_types import (
    BackupResult,
    InputFile,
)
from ethernity.workflows.shared.paths import expanduser_cli_paths
from ethernity.workflows.shared.requests import (
    BackupRequest,
    RebuildRequest,
    RecoveryRequest,
)


@dataclass(frozen=True)
class _RecoverySheetSettings:
    passphrase_shard_threshold: int | None
    passphrase_shard_count: int
    signing_key_shard_threshold: int | None
    signing_key_shard_count: int


@dataclass(frozen=True)
class _RebuildSourceHead:
    root_doc_id: bytes
    root_doc_hash: bytes
    selected_extension_index: int | None
    selected_extension_doc_hash: str | None


def _validated_rebuild_root_dir(root_dir_value: str | Path | None) -> Path:
    if not root_dir_value:
        raise ValueError("rebuild requires a backup folder or scanned documents")
    root_dir = Path(root_dir_value).expanduser()
    if root_dir.is_symlink():
        raise ValueError(f"backup source folder must not be a symlink: {root_dir_value}")
    if not root_dir.exists():
        raise ValueError(f"backup source folder not found: {root_dir_value}")
    if not root_dir.is_dir():
        raise ValueError(f"backup source must be a directory: {root_dir_value}")
    return root_dir


def validate_rebuild_source_selection(args: RebuildRequest) -> None:
    """Validate that rebuild has exactly one source mode."""

    has_root_dir = bool(args.backup_folder)
    has_scan = bool(args.scan_paths)
    if has_root_dir and has_scan:
        raise ValueError("use either a backup folder or scanned documents for rebuild, not both")
    if not has_root_dir and not has_scan:
        raise ValueError("rebuild requires a backup folder or scanned documents")
    if args.expected_head_doc_hash is None and not args.allow_stale_head:
        raise ValueError(
            "rebuild cannot prove the supplied documents are the latest chain state; "
            "provide an expected latest backup fingerprint or acknowledge that newer documents "
            "may be missing"
        )


def _reject_rebuild_output_inside_root(root_dir: Path, output_dir_value: str | Path) -> None:
    output_dir = Path(output_dir_value).expanduser()
    root_resolved = root_dir.resolve(strict=False)
    output_resolved = output_dir.resolve(strict=False)
    if output_resolved == root_resolved or output_resolved.is_relative_to(root_resolved):
        raise ValueError(
            "rebuild output directory must not be the source folder or inside it: "
            f"{output_dir_value}"
        )


def _reject_rebuild_layout_debug_inside_root(
    root_dir: Path, layout_debug_dir_value: str | Path | None
) -> None:
    if layout_debug_dir_value is None or not str(layout_debug_dir_value).strip():
        return
    debug_dir = Path(layout_debug_dir_value).expanduser()
    root_resolved = root_dir.resolve(strict=False)
    debug_resolved = debug_dir.resolve(strict=False)
    if debug_resolved == root_resolved or debug_resolved.is_relative_to(root_resolved):
        raise ValueError(
            "rebuild layout debug directory must not be the source folder "
            f"or inside it: {layout_debug_dir_value}"
        )


def _translate_rebuild_head_untrusted(
    exc: ApiCommandError | ExtensionRecoveryError,
) -> ApiCommandError:
    head_label = "requested" if exc.details.get("explicit_selection") else "latest supplied"
    message = f"{head_label} rebuild head could not be trusted; no rebuilt backup was created"
    failure_message = exc.details.get("failure_message")
    if isinstance(failure_message, str) and failure_message:
        message = f"{message}: {failure_message}"
    details = dict(exc.details)
    details["backup_created"] = False
    return ApiCommandError(code=exc.code, message=message, details=details)


def _recovery_request_for_rebuild(args: RebuildRequest, root_dir: Path | None) -> RecoveryRequest:
    scan_paths = args.scan_paths or ((str(root_dir),) if root_dir is not None else ())
    return replace(
        args.recovery_request(),
        scan_paths=scan_paths,
        auth_frames=args.auth_frames,
        expected_head_doc_hash=args.expected_head_doc_hash,
        quiet=args.quiet,
    )


def _recover_rebuild_chain(recover_plan):
    try:
        return recover_chain_entries(recover_plan, debug=False)
    except (ApiCommandError, ExtensionRecoveryError) as exc:
        if exc.code != issue_codes.RECOVERY_HEAD_UNTRUSTED:
            raise
        raise _translate_rebuild_head_untrusted(exc) from exc


def _rebuild_source_head(recover_plan, chain) -> _RebuildSourceHead:
    return _RebuildSourceHead(
        root_doc_id=recover_plan.doc_id,
        root_doc_hash=recover_plan.doc_hash,
        selected_extension_index=getattr(chain, "selected_extension_index", None),
        selected_extension_doc_hash=getattr(chain, "selected_extension_doc_hash", None),
    )


def _infer_recovery_sheet_settings(
    *,
    root_dir: str | None,
    source_scan: Sequence[str | Path] = (),
    root_doc_id_hex: str | None,
    root_doc_hash: bytes,
    sign_pub: bytes | None,
    passphrase_shard_frames: Sequence[Frame] = (),
    signing_key_shard_frames: Sequence[Frame] = (),
    require_quorum: bool = True,
) -> _RecoverySheetSettings:
    scan_inputs = tuple(source_scan) or ((root_dir,) if root_dir else ())
    source_key_frames = _key_frames_from_source_scan(scan_inputs) if scan_inputs else ()
    root_doc_id = bytes.fromhex(root_doc_id_hex) if root_doc_id_hex else None
    policy_frames = (
        *source_key_frames,
        *tuple(passphrase_shard_frames),
        *tuple(signing_key_shard_frames),
    )
    if sign_pub is None:
        if has_potential_root_shard_frames(
            policy_frames,
            expected_doc_id=root_doc_id,
            expected_doc_hash=root_doc_hash,
        ):
            raise ApiCommandError(
                code=issue_codes.REBUILD_INVALID_POLICY,
                message=(
                    "rebuild cannot inherit root shard policy without a verified root signing key"
                ),
                details={"stage": "root_shard_policy"},
            )
        return _RecoverySheetSettings(
            passphrase_shard_threshold=None,
            passphrase_shard_count=0,
            signing_key_shard_threshold=None,
            signing_key_shard_count=0,
        )
    if root_doc_id is None:
        raise ApiCommandError(
            code=issue_codes.REBUILD_INVALID_POLICY,
            message="rebuild cannot inherit root shard policy without a root document id",
            details={"stage": "root_shard_policy"},
        )
    passphrase_threshold, passphrase_count = _infer_root_quorum(
        policy_frames,
        expected_doc_id=root_doc_id,
        expected_doc_hash=root_doc_hash,
        sign_pub=sign_pub,
        require_quorum=require_quorum,
        key_type=sharding_module.KEY_TYPE_PASSPHRASE,
        secret_label="passphrase",
    )
    signing_key_threshold, signing_key_count = _infer_root_quorum(
        policy_frames,
        expected_doc_id=root_doc_id,
        expected_doc_hash=root_doc_hash,
        sign_pub=sign_pub,
        require_quorum=require_quorum,
        key_type=sharding_module.KEY_TYPE_SIGNING_SEED,
        secret_label="signing key",
    )
    return _RecoverySheetSettings(
        passphrase_shard_threshold=passphrase_threshold,
        passphrase_shard_count=passphrase_count,
        signing_key_shard_threshold=signing_key_threshold,
        signing_key_shard_count=signing_key_count,
    )


def _infer_root_quorum(
    frames: Sequence[Frame],
    *,
    expected_doc_id: bytes,
    expected_doc_hash: bytes,
    sign_pub: bytes,
    require_quorum: bool = True,
    key_type: str,
    secret_label: str,
) -> tuple[int | None, int]:
    if not frames:
        return None, 0
    try:
        return root_shard_quorum_from_frames(
            frames,
            expected_doc_id=expected_doc_id,
            expected_doc_hash=expected_doc_hash,
            sign_pub=sign_pub,
            key_type=key_type,
            secret_label=secret_label,
            require_quorum=require_quorum,
        )
    except InsufficientShardError as exc:
        raise ApiCommandError(
            code=issue_codes.REBUILD_INVALID_POLICY,
            message=(
                f"root {secret_label} shards are under quorum; "
                f"need at least {exc.threshold}, found {exc.provided_count}"
            ),
        ) from exc
    except ValueError as exc:
        raise ApiCommandError(
            code=issue_codes.REBUILD_INVALID_POLICY,
            message=str(exc),
            details={"stage": "root_shard_policy"},
        ) from exc


def _key_frames_from_source_scan(
    source_scan: Sequence[str | Path],
) -> tuple[Frame, ...]:
    try:
        frames = frames_from_scan(expanduser_cli_paths(source_scan))
    except ValueError as exc:
        raise ApiCommandError(
            code=issue_codes.REBUILD_INVALID_POLICY,
            message=f"root shard policy scan failed: {exc}",
            details={"stage": "root_shard_policy"},
        ) from exc
    return tuple(frame for frame in frames if frame.frame_type == FrameType.KEY_DOCUMENT)


def execute_rebuild_operation(args: RebuildRequest) -> BackupResult:
    emit_phase(phase="source", label="Resolving Rebuild sources")
    validate_rebuild_source_selection(args)
    root_dir = None if args.scan_paths else _validated_rebuild_root_dir(args.backup_folder)
    emit_phase(phase="output", label="Checking Rebuild destination")
    if not args.output_dir:
        raise ValueError("rebuild requires output_dir")
    if root_dir is not None:
        _reject_rebuild_output_inside_root(root_dir, args.output_dir)
        _reject_rebuild_layout_debug_inside_root(root_dir, args.layout_debug_dir)

    recover_plan = plan_recovery_request(_recovery_request_for_rebuild(args, root_dir))
    chain = _recover_rebuild_chain(recover_plan)
    source_head = _rebuild_source_head(recover_plan, chain)
    manifest = chain.manifest

    sign_pub = (
        derive_public_key(manifest.signing_seed)
        if manifest.signing_seed is not None
        else (recover_plan.auth_payload.sign_pub if recover_plan.auth_payload is not None else None)
    )
    selected_extension_doc_hash = getattr(chain, "selected_extension_doc_hash", None)
    unlock_passphrase_frames = _passphrase_shard_frames_for_selected_head(
        recover_plan.shard_frames,
        root_doc_id=recover_plan.doc_id,
        root_doc_hash=recover_plan.doc_hash,
        selected_extension_doc_hash=selected_extension_doc_hash,
    )
    unlock_doc_hash = (
        bytes.fromhex(selected_extension_doc_hash)
        if selected_extension_doc_hash
        else recover_plan.doc_hash
    )
    unlock_doc_id = (
        doc_id_from_doc_hash(unlock_doc_hash)
        if selected_extension_doc_hash
        else recover_plan.doc_id
    )
    unlock_passphrase_policy = _infer_passphrase_shard_policy_from_frames(
        unlock_passphrase_frames,
        sign_pub=sign_pub,
        expected_doc_id=unlock_doc_id,
        expected_doc_hash=unlock_doc_hash,
    )

    inherited = _infer_recovery_sheet_settings(
        root_dir=str(root_dir) if root_dir is not None else None,
        source_scan=tuple(args.scan_paths or ()),
        root_doc_id_hex=recover_plan.doc_id.hex(),
        root_doc_hash=recover_plan.doc_hash,
        sign_pub=sign_pub,
        passphrase_shard_frames=_passphrase_shard_frames_for_doc(
            recover_plan.shard_frames,
            expected_doc_id=recover_plan.doc_id,
            expected_doc_hash=recover_plan.doc_hash,
        ),
    )
    if unlock_passphrase_policy is not None:
        inherited = _RecoverySheetSettings(
            passphrase_shard_threshold=unlock_passphrase_policy[0],
            passphrase_shard_count=unlock_passphrase_policy[1],
            signing_key_shard_threshold=inherited.signing_key_shard_threshold,
            signing_key_shard_count=inherited.signing_key_shard_count,
        )
    if (
        not manifest.sealed
        and inherited.signing_key_shard_count > 0
        and (inherited.passphrase_shard_count <= 0 or inherited.passphrase_shard_threshold is None)
    ):
        raise ValueError(
            "root backup signing-key shards require passphrase shards; "
            "rebuild cannot preserve an invalid shard policy"
        )
    backup_args = BackupRequest(
        config_path=args.config_path,
        paper_size=args.paper_size,
        design=args.design,
        output_dir=args.output_dir,
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
    config = load_app_config(backup_args.config_path, paper_size=backup_args.paper_size)
    config = apply_render_style(config, backup_args.design)
    config = apply_qr_chunk_size_override(config, backup_args.qr_chunk_size)
    backup_plan = plan_backup_request(backup_args)
    input_files = [
        InputFile(
            source_path=None,
            relative_path=entry.path,
            data=data,
            mtime=entry.mtime,
        )
        for entry, data in chain.extracted
    ]
    result = run_backup(
        input_files=input_files,
        base_dir=None,
        output_dir=backup_args.output_dir,
        layout_debug_dir=backup_args.layout_debug_dir,
        input_origin=manifest.input_origin,
        input_roots=list(manifest.input_roots),
        plan=backup_plan,
        passphrase=backup_args.passphrase,
        config=config,
        signing_seed_override=None if manifest.sealed else manifest.signing_seed,
        payload_codec_override="auto",
        render_origin=DocumentOrigin(kind="rebuilt_backup"),
        publication_durability="required",
        quiet=args.quiet,
    )
    return replace(
        result,
        signing_key_preserved=not manifest.sealed,
        source_head_index=source_head.selected_extension_index or 0,
        source_head_doc_hash=source_head.selected_extension_doc_hash or recover_plan.doc_hash.hex(),
        expected_head_doc_hash=args.expected_head_doc_hash,
        freshness_scope=(
            "supplied_carriers_only"
            if source_head.selected_extension_index is not None
            or args.expected_head_doc_hash is not None
            else None
        ),
    )


def _passphrase_shard_frames_for_doc(
    frames: Sequence[Frame],
    *,
    expected_doc_id: bytes,
    expected_doc_hash: bytes,
) -> tuple[Frame, ...]:
    return _passphrase_shard_frames_for_document(
        frames,
        expected_doc_id=expected_doc_id,
        expected_doc_hash=expected_doc_hash,
    )


def _passphrase_shard_frames_for_selected_head(
    frames: Sequence[Frame],
    *,
    root_doc_id: bytes,
    root_doc_hash: bytes,
    selected_extension_doc_hash: str | None,
) -> tuple[Frame, ...]:
    if selected_extension_doc_hash:
        selected_doc_hash = bytes.fromhex(selected_extension_doc_hash)
        return _passphrase_shard_frames_for_document(
            frames,
            expected_doc_id=doc_id_from_doc_hash(selected_doc_hash),
            expected_doc_hash=selected_doc_hash,
            strict_doc_id=True,
        )
    return _passphrase_shard_frames_for_document(
        frames,
        expected_doc_id=root_doc_id,
        expected_doc_hash=root_doc_hash,
    )


def _passphrase_shard_frames_for_document(
    frames: Sequence[Frame],
    *,
    expected_doc_id: bytes | None,
    expected_doc_hash: bytes,
    strict_doc_id: bool = False,
) -> tuple[Frame, ...]:
    selected: list[Frame] = []
    for frame, payload in decoded_shard_candidates(frames):
        if payload.key_type != sharding_module.KEY_TYPE_PASSPHRASE:
            continue
        if payload.doc_hash != expected_doc_hash:
            continue
        if expected_doc_id is not None and frame.doc_id != expected_doc_id:
            if strict_doc_id:
                raise ApiCommandError(
                    code=issue_codes.REBUILD_INVALID_POLICY,
                    message="source passphrase shard frame doc_id does not match selected document",
                    details={"stage": "source_shard_policy"},
                )
            continue
        selected.append(frame)
    return tuple(selected)


def _infer_passphrase_shard_policy_from_frames(
    frames: Sequence[Frame],
    *,
    sign_pub: bytes | None,
    expected_doc_id: bytes | None = None,
    expected_doc_hash: bytes | None = None,
) -> tuple[int, int] | None:
    passphrase_frames: list[Frame] = []
    for frame in frames:
        if frame.frame_type != FrameType.KEY_DOCUMENT:
            continue
        try:
            payload = sharding_module.decode_shard_payload(frame.data)
        except ValueError:
            continue
        if payload.key_type == sharding_module.KEY_TYPE_PASSPHRASE:
            passphrase_frames.append(frame)
    if not passphrase_frames:
        return None
    if sign_pub is None:
        raise ApiCommandError(
            code=issue_codes.REBUILD_INVALID_POLICY,
            message=(
                "rebuild cannot inherit source passphrase shard policy without a verified "
                "root signing key"
            ),
            details={"stage": "source_shard_policy"},
        )

    try:
        shares = validated_shard_payloads_from_frames(
            passphrase_frames,
            expected_doc_id=expected_doc_id,
            expected_doc_hash=expected_doc_hash,
            expected_sign_pub=sign_pub,
            allow_unsigned=False,
            key_type=sharding_module.KEY_TYPE_PASSPHRASE,
            secret_label="passphrase",
        )
    except InsufficientShardError as exc:
        if exc.share_count is not None:
            return exc.threshold, exc.share_count
        raise ApiCommandError(
            code=issue_codes.REBUILD_INVALID_POLICY,
            message=(
                "source passphrase shards are under quorum; "
                f"need at least {exc.threshold}, found {exc.provided_count}"
            ),
        ) from exc
    first = shares[0]
    return first.threshold, first.share_count
