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

"""Build validated recovery execution plans from CLI inputs."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal

from ethernity.cli.features.recover.key_recovery import (
    InsufficientShardError,
    _passphrase_from_shard_frames,
    _resolve_auth_payload,
    _resolve_recovery_keys,
    _validated_shard_payloads_from_frames,
)
from ethernity.cli.shared import api_codes
from ethernity.cli.shared.crypto import _doc_id_and_hash_from_ciphertext
from ethernity.cli.shared.io.fallback_parser import format_fallback_error
from ethernity.cli.shared.io.frames import (
    _auth_frames_from_fallback,
    _auth_frames_from_payloads,
    _dedupe_auth_frames,
    _dedupe_frames,
    _frame_from_fallback,
    _frames_from_fallback,
    _frames_from_payloads,
    _recovery_frames_from_scan,
    _shard_frames_from_scan,
    _split_main_and_auth_frames,
    format_recovery_input_error,
    format_shard_input_error,
)
from ethernity.cli.shared.log import _warn
from ethernity.cli.shared.paths import expanduser_cli_path, expanduser_cli_paths
from ethernity.cli.shared.types import RecoverArgs
from ethernity.config import load_app_config
from ethernity.crypto.passphrases import (
    normalize_bip39_mnemonic,
    validate_mnemonic_checksum_if_bip39,
)
from ethernity.crypto.sharding import KEY_TYPE_PASSPHRASE
from ethernity.crypto.signing import AuthPayload, decode_auth_payload, verify_auth
from ethernity.encoding.chunking import reassemble_payload
from ethernity.encoding.framing import Frame, FrameType


@dataclass(frozen=True)
class RecoveryPlan:
    """Resolved recovery inputs, verification state, and output preferences."""

    ciphertext: bytes
    doc_id: bytes
    doc_hash: bytes
    passphrase: str
    auth_payload: AuthPayload | None
    auth_status: str
    allow_unsigned: bool
    output_path: str | None
    input_label: str | None
    input_detail: str | None
    main_frames: tuple[Frame, ...]
    auth_frames: tuple[Frame, ...]
    shard_frames: tuple[Frame, ...]
    shard_fallback_files: tuple[str, ...]
    shard_payloads_file: tuple[str, ...]
    shard_scan: tuple[str, ...]


@dataclass(frozen=True)
class RecoveryUnlockStatus:
    """Unlock readiness for API inspection flows."""

    mode: Literal["missing", "passphrase", "shards"]
    passphrase_provided: bool
    validated_shard_count: int
    required_shard_threshold: int | None
    satisfied: bool
    resolved_passphrase: str | None = None
    blocking_issues: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class RecoveryInspection:
    """Best-effort recovery inspection state used by API inspect flows."""

    ciphertext: bytes
    doc_id: bytes
    doc_hash: bytes
    auth_payload: AuthPayload | None
    auth_status: str
    allow_unsigned: bool
    input_label: str | None
    input_detail: str | None
    main_frames: tuple[Frame, ...]
    auth_frames: tuple[Frame, ...]
    shard_frames: tuple[Frame, ...]
    shard_fallback_files: tuple[str, ...]
    shard_payloads_file: tuple[str, ...]
    shard_scan: tuple[str, ...]
    unlock: RecoveryUnlockStatus
    blocking_issues: tuple[dict[str, Any], ...]


def resolve_recover_config(args: RecoverArgs) -> object:
    """Load recovery-related config to validate config/paper inputs early."""

    config = load_app_config(args.config, paper_size=args.paper)
    return config


def validate_recover_args(args: RecoverArgs) -> None:
    """Validate mutually exclusive recovery input flags."""

    if args.fallback_file and args.payloads_file:
        raise ValueError("use either --fallback-file or --payloads-file, not both")
    if args.scan and (args.fallback_file or args.payloads_file):
        raise ValueError("use either --scan or --fallback-file/--payloads-file, not both")
    if args.auth_fallback_file and args.auth_payloads_file:
        raise ValueError("use either --auth-fallback-file or --auth-payloads-file, not both")


def inspect_from_args(args: RecoverArgs) -> RecoveryInspection:
    """Build a best-effort recovery inspection directly from CLI arguments."""

    validate_recover_args(args)
    resolve_recover_config(args)
    allow_unsigned = args.allow_unsigned
    quiet = args.quiet

    frames, input_label, input_detail = _frames_from_args(
        args,
        allow_unsigned=allow_unsigned,
        quiet=quiet,
    )
    extra_auth_frames = _extra_auth_frames_from_args(
        args,
        allow_unsigned=allow_unsigned,
        quiet=quiet,
    )
    shard_frames, shard_fallback_files, shard_payloads_file, shard_scan = _shard_frames_from_args(
        args,
        quiet=quiet,
    )
    return inspect_recovery_inputs(
        frames=frames,
        extra_auth_frames=extra_auth_frames,
        shard_frames=shard_frames,
        passphrase=args.passphrase,
        allow_unsigned=allow_unsigned,
        input_label=input_label,
        input_detail=input_detail,
        shard_fallback_files=shard_fallback_files,
        shard_payloads_file=shard_payloads_file,
        shard_scan=shard_scan,
        quiet=quiet,
    )


def plan_from_args(args: RecoverArgs) -> RecoveryPlan:
    """Build a full recovery plan directly from CLI arguments."""

    validate_recover_args(args)
    resolve_recover_config(args)
    allow_unsigned = args.allow_unsigned
    quiet = args.quiet

    frames, input_label, input_detail = _frames_from_args(
        args,
        allow_unsigned=allow_unsigned,
        quiet=quiet,
    )
    extra_auth_frames = _extra_auth_frames_from_args(
        args,
        allow_unsigned=allow_unsigned,
        quiet=quiet,
    )
    shard_frames, shard_fallback_files, shard_payloads_file, shard_scan = _shard_frames_from_args(
        args,
        quiet=quiet,
    )
    return build_recovery_plan(
        frames=frames,
        extra_auth_frames=extra_auth_frames,
        shard_frames=shard_frames,
        passphrase=args.passphrase,
        allow_unsigned=allow_unsigned,
        input_label=input_label,
        input_detail=input_detail,
        shard_fallback_files=shard_fallback_files,
        shard_payloads_file=shard_payloads_file,
        shard_scan=shard_scan,
        output_path=expanduser_cli_path(args.output),
        args=args,
        quiet=quiet,
    )


def inspect_recovery_inputs(
    *,
    frames: list[Frame],
    extra_auth_frames: list[Frame],
    shard_frames: list[Frame],
    passphrase: str | None,
    allow_unsigned: bool,
    input_label: str | None,
    input_detail: str | None,
    shard_fallback_files: list[str],
    shard_payloads_file: list[str],
    shard_scan: list[str],
    quiet: bool,
) -> RecoveryInspection:
    """Assemble best-effort recovery inspection state from decoded frames."""

    if not frames:
        hint = "Check the input path and try again."
        if input_label == "Scan":
            hint = "Check the scan path and image quality, then try again."
        raise ValueError(f"no payloads found. {hint}")

    deduped = _dedupe_frames(frames)
    main_frames, auth_frames = _split_main_and_auth_frames(deduped)
    if extra_auth_frames:
        auth_frames = _dedupe_auth_frames([*auth_frames, *extra_auth_frames])

    ciphertext = reassemble_payload(main_frames, expected_frame_type=FrameType.MAIN_DOCUMENT)
    doc_id, doc_hash = _doc_id_and_hash_from_ciphertext(ciphertext)
    auth_payload, auth_status, auth_blocking_issues = _inspect_auth_payload(
        auth_frames,
        doc_id=doc_id,
        doc_hash=doc_hash,
        allow_unsigned=allow_unsigned,
        require_auth=not allow_unsigned and not shard_frames,
        quiet=quiet,
    )
    unlock = _inspect_unlock_status(
        passphrase=passphrase,
        shard_frames=shard_frames,
        doc_id=doc_id,
        doc_hash=doc_hash,
        sign_pub=auth_payload.sign_pub if auth_payload is not None else None,
        allow_unsigned=allow_unsigned,
    )
    if auth_blocking_issues and unlock.satisfied:
        unlock = replace(unlock, satisfied=False, resolved_passphrase=None)
    blocking_issues = [*auth_blocking_issues, *unlock.blocking_issues]
    return RecoveryInspection(
        ciphertext=ciphertext,
        doc_id=doc_id,
        doc_hash=doc_hash,
        auth_payload=auth_payload,
        auth_status=auth_status,
        allow_unsigned=allow_unsigned,
        input_label=input_label,
        input_detail=input_detail,
        main_frames=tuple(main_frames),
        auth_frames=tuple(auth_frames),
        shard_frames=tuple(shard_frames),
        shard_fallback_files=tuple(shard_fallback_files),
        shard_payloads_file=tuple(shard_payloads_file),
        shard_scan=tuple(shard_scan),
        unlock=unlock,
        blocking_issues=tuple(blocking_issues),
    )


def build_recovery_plan(
    *,
    frames: list[Frame],
    extra_auth_frames: list[Frame],
    shard_frames: list[Frame],
    passphrase: str | None,
    allow_unsigned: bool,
    input_label: str | None,
    input_detail: str | None,
    shard_fallback_files: list[str],
    shard_payloads_file: list[str],
    shard_scan: list[str],
    output_path: str | None,
    args: RecoverArgs | None,
    quiet: bool,
) -> RecoveryPlan:
    """Assemble a validated recovery plan from decoded frames and key inputs."""

    if not frames:
        hint = "Check the input path and try again."
        if input_label == "Scan":
            hint = "Check the scan path and image quality, then try again."
        raise ValueError(f"no payloads found. {hint}")

    deduped = _dedupe_frames(frames)
    main_frames, auth_frames = _split_main_and_auth_frames(deduped)
    if extra_auth_frames:
        auth_frames = _dedupe_auth_frames([*auth_frames, *extra_auth_frames])

    ciphertext = reassemble_payload(main_frames, expected_frame_type=FrameType.MAIN_DOCUMENT)
    doc_id, doc_hash = _doc_id_and_hash_from_ciphertext(ciphertext)

    auth_payload, auth_status = _resolve_auth_payload(
        auth_frames,
        doc_id=doc_id,
        doc_hash=doc_hash,
        allow_unsigned=allow_unsigned,
        require_auth=not allow_unsigned and not shard_frames,
        quiet=quiet,
    )
    sign_pub = auth_payload.sign_pub if auth_payload else None
    resolved_passphrase = _resolve_passphrase(
        passphrase=passphrase,
        shard_frames=shard_frames,
        doc_id=doc_id,
        doc_hash=doc_hash,
        sign_pub=sign_pub,
        allow_unsigned=allow_unsigned,
        args=args,
    )

    return RecoveryPlan(
        ciphertext=ciphertext,
        doc_id=doc_id,
        doc_hash=doc_hash,
        passphrase=resolved_passphrase,
        auth_payload=auth_payload,
        auth_status=auth_status,
        allow_unsigned=allow_unsigned,
        output_path=output_path,
        input_label=input_label,
        input_detail=input_detail,
        main_frames=tuple(main_frames),
        auth_frames=tuple(auth_frames),
        shard_frames=tuple(shard_frames),
        shard_fallback_files=tuple(shard_fallback_files),
        shard_payloads_file=tuple(shard_payloads_file),
        shard_scan=tuple(shard_scan),
    )


def _blocking_issue(
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "details": details or {},
    }


def _inspect_auth_payload(
    auth_frames: list[Frame],
    *,
    doc_id: bytes,
    doc_hash: bytes,
    allow_unsigned: bool,
    require_auth: bool,
    quiet: bool,
) -> tuple[AuthPayload | None, str, tuple[dict[str, Any], ...]]:
    if not auth_frames:
        if require_auth:
            return (
                None,
                "missing",
                (
                    _blocking_issue(
                        api_codes.AUTH_PAYLOAD_MISSING,
                        "missing auth payload; provide AUTH input for inspection readiness",
                    ),
                ),
            )
        if allow_unsigned:
            _warn(
                "no auth payload provided; skipping auth verification",
                quiet=quiet,
                code=api_codes.AUTH_PAYLOAD_MISSING,
            )
            return None, "skipped", ()
        return None, "missing", ()
    if len(auth_frames) > 1:
        return (
            None,
            "invalid",
            (_blocking_issue("AUTH_PAYLOAD_MULTIPLE", "multiple auth payloads provided"),),
        )

    frame = auth_frames[0]
    if frame.doc_id != doc_id:
        if allow_unsigned:
            _warn(
                "auth payload doc_id mismatch; verification skipped",
                quiet=quiet,
                code=api_codes.AUTH_PAYLOAD_INVALID,
                details={"reason": "doc_id_mismatch"},
            )
            return None, "ignored", ()
        return (
            None,
            "invalid",
            (
                _blocking_issue(
                    "AUTH_PAYLOAD_DOC_ID_MISMATCH",
                    "auth payload doc_id does not match ciphertext",
                ),
            ),
        )
    if frame.total != 1 or frame.index != 0:
        return (
            None,
            "invalid",
            (
                _blocking_issue(
                    "AUTH_PAYLOAD_FRAME_INVALID",
                    "auth payload must be a single-frame payload",
                ),
            ),
        )

    try:
        payload = decode_auth_payload(frame.data)
    except ValueError as exc:
        if allow_unsigned:
            _warn(
                f"invalid auth payload; verification skipped: {exc}",
                quiet=quiet,
                code=api_codes.AUTH_PAYLOAD_INVALID,
                details={"reason": str(exc)},
            )
            return None, "invalid", ()
        return (
            None,
            "invalid",
            (
                _blocking_issue(
                    api_codes.AUTH_PAYLOAD_INVALID,
                    f"invalid auth payload: {exc}",
                    details={"reason": str(exc)},
                ),
            ),
        )
    if payload.doc_hash != doc_hash:
        if allow_unsigned:
            _warn(
                "auth doc_hash mismatch; verification skipped",
                quiet=quiet,
                code=api_codes.AUTH_DOC_HASH_MISMATCH,
            )
            return None, "ignored", ()
        return (
            None,
            "ignored",
            (
                _blocking_issue(
                    api_codes.AUTH_DOC_HASH_MISMATCH,
                    "auth doc_hash does not match ciphertext",
                ),
            ),
        )
    if not verify_auth(doc_hash, sign_pub=payload.sign_pub, signature=payload.signature):
        if allow_unsigned:
            _warn(
                "auth signature verification failed; verification skipped",
                quiet=quiet,
                code=api_codes.AUTH_SIGNATURE_INVALID,
            )
            return None, "ignored", ()
        return (
            None,
            "ignored",
            (
                _blocking_issue(
                    api_codes.AUTH_SIGNATURE_INVALID,
                    "invalid auth signature",
                ),
            ),
        )
    return payload, "verified", ()


def _inspect_unlock_status(
    *,
    passphrase: str | None,
    shard_frames: list[Frame],
    doc_id: bytes,
    doc_hash: bytes,
    sign_pub: bytes | None,
    allow_unsigned: bool,
) -> RecoveryUnlockStatus:
    if shard_frames and passphrase:
        raise ValueError("use either shard inputs or passphrase, not both")
    if shard_frames:
        try:
            shard_payloads = _validated_shard_payloads_from_frames(
                shard_frames,
                expected_doc_id=doc_id,
                expected_doc_hash=doc_hash,
                expected_sign_pub=sign_pub,
                allow_unsigned=allow_unsigned,
                key_type=KEY_TYPE_PASSPHRASE,
                secret_label="passphrase",
            )
        except InsufficientShardError as exc:
            return RecoveryUnlockStatus(
                mode="shards",
                passphrase_provided=False,
                validated_shard_count=exc.provided_count,
                required_shard_threshold=exc.threshold,
                satisfied=False,
                blocking_issues=(
                    _blocking_issue(
                        "PASSPHRASE_SHARDS_UNDER_QUORUM",
                        f"need at least {exc.threshold} shard(s) to recover passphrase",
                        details={
                            "provided_count": exc.provided_count,
                            "required_threshold": exc.threshold,
                        },
                    ),
                ),
            )
        except ValueError as exc:
            return RecoveryUnlockStatus(
                mode="shards",
                passphrase_provided=False,
                validated_shard_count=0,
                required_shard_threshold=None,
                satisfied=False,
                blocking_issues=(
                    _blocking_issue(
                        "PASSPHRASE_SHARDS_INVALID",
                        str(exc),
                    ),
                ),
            )
        recovered = _passphrase_from_shard_frames(
            shard_frames,
            expected_doc_id=doc_id,
            expected_doc_hash=doc_hash,
            expected_sign_pub=sign_pub,
            allow_unsigned=allow_unsigned,
        )
        normalized_recovered = normalize_bip39_mnemonic(recovered)
        try:
            validate_mnemonic_checksum_if_bip39(normalized_recovered)
        except ValueError as exc:
            return RecoveryUnlockStatus(
                mode="shards",
                passphrase_provided=False,
                validated_shard_count=len(shard_payloads),
                required_shard_threshold=shard_payloads[0].threshold if shard_payloads else None,
                satisfied=False,
                blocking_issues=(
                    _blocking_issue(
                        "PASSPHRASE_INVALID",
                        str(exc),
                    ),
                ),
            )
        return RecoveryUnlockStatus(
            mode="shards",
            passphrase_provided=False,
            validated_shard_count=len(shard_payloads),
            required_shard_threshold=shard_payloads[0].threshold if shard_payloads else None,
            satisfied=True,
            resolved_passphrase=normalized_recovered,
        )
    if passphrase:
        normalized_passphrase = normalize_bip39_mnemonic(passphrase)
        try:
            validate_mnemonic_checksum_if_bip39(normalized_passphrase)
        except ValueError as exc:
            return RecoveryUnlockStatus(
                mode="passphrase",
                passphrase_provided=True,
                validated_shard_count=0,
                required_shard_threshold=None,
                satisfied=False,
                blocking_issues=(
                    _blocking_issue(
                        "PASSPHRASE_INVALID",
                        str(exc),
                    ),
                ),
            )
        return RecoveryUnlockStatus(
            mode="passphrase",
            passphrase_provided=True,
            validated_shard_count=0,
            required_shard_threshold=None,
            satisfied=True,
            resolved_passphrase=normalized_passphrase,
        )
    return RecoveryUnlockStatus(
        mode="missing",
        passphrase_provided=False,
        validated_shard_count=0,
        required_shard_threshold=None,
        satisfied=False,
        blocking_issues=(
            _blocking_issue(
                "PASSPHRASE_REQUIRED",
                "passphrase or passphrase shard inputs are required to decrypt this backup",
            ),
        ),
    )


def _resolve_passphrase(
    *,
    passphrase: str | None,
    shard_frames: list[Frame],
    doc_id: bytes,
    doc_hash: bytes,
    sign_pub: bytes | None,
    allow_unsigned: bool,
    args: RecoverArgs | None,
) -> str:
    """Resolve the recovery passphrase from direct input, shards, or arg-driven prompts."""

    if shard_frames and passphrase:
        raise ValueError("use either shard inputs or passphrase, not both")
    if shard_frames:
        recovered = _passphrase_from_shard_frames(
            shard_frames,
            expected_doc_id=doc_id,
            expected_doc_hash=doc_hash,
            expected_sign_pub=sign_pub,
            allow_unsigned=allow_unsigned,
        )
        normalized_recovered = normalize_bip39_mnemonic(recovered)
        validate_mnemonic_checksum_if_bip39(normalized_recovered)
        return normalized_recovered
    if passphrase:
        normalized_passphrase = normalize_bip39_mnemonic(passphrase)
        validate_mnemonic_checksum_if_bip39(normalized_passphrase)
        return normalized_passphrase
    if args is not None:
        recovered = _resolve_recovery_keys(args)
        normalized_recovered = normalize_bip39_mnemonic(recovered)
        validate_mnemonic_checksum_if_bip39(normalized_recovered)
        return normalized_recovered
    raise ValueError("passphrase is required for recovery")


def _frames_from_args(
    args: RecoverArgs,
    *,
    allow_unsigned: bool,
    quiet: bool,
) -> tuple[list[Frame], str | None, str | None]:
    """Load primary recovery frames from fallback text, payload lists, or scans."""

    fallback_file = expanduser_cli_path(args.fallback_file)
    payloads_file = expanduser_cli_path(args.payloads_file)
    scan = expanduser_cli_paths(list(args.scan or []))

    if fallback_file:
        input_label = "Recovery text"
        input_detail = fallback_file
        try:
            frames = _frames_from_fallback(
                fallback_file,
                allow_invalid_auth=allow_unsigned,
                quiet=quiet,
            )
        except ValueError as exc:
            message = str(exc).lower()
            if fallback_file == "-" and "no recovery lines found" in message:
                raise ValueError(
                    "No recovery input found on stdin. Use --fallback-file, --payloads-file, "
                    "--scan, or provide non-empty stdin."
                ) from exc
            raise ValueError(format_fallback_error(exc, context="Recovery text")) from exc
    elif payloads_file:
        input_label = "QR payloads"
        input_detail = payloads_file
        try:
            frames = _frames_from_payloads(payloads_file)
        except ValueError as exc:
            raise ValueError(format_recovery_input_error(exc)) from exc
    elif scan:
        input_label = "Scan"
        input_detail = ", ".join(scan)
        try:
            frames = _recovery_frames_from_scan(scan, quiet=quiet)
        except ValueError as exc:
            raise ValueError(format_recovery_input_error(exc)) from exc
    else:
        raise ValueError("either --fallback-file, --payloads-file, or --scan is required")
    return frames, input_label, input_detail


def _extra_auth_frames_from_args(
    args: RecoverArgs,
    *,
    allow_unsigned: bool,
    quiet: bool,
) -> list[Frame]:
    """Load extra AUTH frames from optional auth-specific inputs."""

    auth_fallback_file = expanduser_cli_path(args.auth_fallback_file)
    auth_payloads_file = expanduser_cli_path(args.auth_payloads_file)
    if auth_fallback_file and auth_payloads_file:
        raise ValueError("use either --auth-fallback-file or --auth-payloads-file, not both")
    extra_auth_frames: list[Frame] = []
    if auth_fallback_file:
        try:
            extra_auth_frames.extend(
                _auth_frames_from_fallback(
                    auth_fallback_file,
                    allow_invalid_auth=allow_unsigned,
                    quiet=quiet,
                )
            )
        except ValueError as exc:
            raise ValueError(format_fallback_error(exc, context="Auth recovery text")) from exc
    if auth_payloads_file:
        extra_auth_frames.extend(_auth_frames_from_payloads(auth_payloads_file))
    return extra_auth_frames


def _shard_frames_from_args(
    args: RecoverArgs,
    *,
    quiet: bool,
) -> tuple[list[Frame], list[str], list[str], list[str]]:
    """Load shard frames from shard fallback and payload inputs."""

    shard_fallback_files = expanduser_cli_paths(list(args.shard_fallback_file or []))
    shard_payloads_file = expanduser_cli_paths(list(args.shard_payloads_file or []))
    shard_scan = expanduser_cli_paths(list(args.shard_scan or []))
    shard_frames: list[Frame] = []
    for path in shard_fallback_files:
        try:
            shard_frames.append(_frame_from_fallback(path, quiet=quiet))
        except ValueError as exc:
            raise ValueError(format_fallback_error(exc, context="Shard recovery text")) from exc
    for path in shard_payloads_file:
        try:
            shard_frames.extend(_frames_from_payloads(path, label="shard QR payloads"))
        except ValueError as exc:
            raise ValueError(format_shard_input_error(exc)) from exc
    if shard_scan:
        try:
            shard_frames.extend(_shard_frames_from_scan(shard_scan, quiet=quiet))
        except ValueError as exc:
            raise ValueError(format_shard_input_error(exc)) from exc
    if (shard_fallback_files or shard_payloads_file or shard_scan) and not shard_frames:
        raise ValueError("no shard payloads found; check shard inputs and try again")
    return shard_frames, shard_fallback_files, shard_payloads_file, shard_scan
