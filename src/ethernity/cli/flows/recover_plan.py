#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass

from ...config import load_app_config
from ...crypto.signing import AuthPayload
from ...encoding.chunking import reassemble_payload
from ...encoding.framing import Frame, FrameType
from ..core.crypto import _doc_hash_from_ciphertext, _doc_id_from_ciphertext
from ..core.log import _warn
from ..core.types import RecoverArgs
from ..io.fallback_parser import format_fallback_error
from ..io.frames import (
    _auth_frames_from_fallback,
    _auth_frames_from_payloads,
    _dedupe_auth_frames,
    _dedupe_frames,
    _frames_from_fallback,
    _frames_from_payloads,
    _frames_from_scan,
    _frames_from_shard_inputs,
    _split_main_and_auth_frames,
)
from ..keys.recover_keys import (
    _passphrase_from_shard_frames,
    _resolve_auth_payload,
    _resolve_recovery_keys,
)


@dataclass(frozen=True)
class RecoveryPlan:
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


def resolve_recover_config(args: RecoverArgs) -> tuple[object, str]:
    if args.config and args.paper:
        raise ValueError("use either --config or --paper, not both")
    config = load_app_config(args.config, paper_size=args.paper)
    return config, config.qr_payload_encoding


def validate_recover_args(args: RecoverArgs) -> None:
    if args.fallback_file and args.payloads_file:
        raise ValueError("use either --fallback-file or --payloads-file, not both")
    if args.scan and (args.fallback_file or args.payloads_file):
        raise ValueError("use either --scan or --fallback-file/--payloads-file, not both")
    if args.auth_fallback_file and args.auth_payloads_file:
        raise ValueError("use either --auth-fallback-file or --auth-payloads-file, not both")


def plan_from_args(args: RecoverArgs) -> RecoveryPlan:
    validate_recover_args(args)
    _, qr_payload_encoding = resolve_recover_config(args)
    allow_unsigned = args.allow_unsigned
    quiet = args.quiet
    if allow_unsigned:
        _warn("Authentication check skipped - ensure you trust the source", quiet=quiet)

    frames, input_label, input_detail = _frames_from_args(
        args,
        qr_payload_encoding=qr_payload_encoding,
        allow_unsigned=allow_unsigned,
        quiet=quiet,
    )
    extra_auth_frames = _extra_auth_frames_from_args(
        args,
        allow_unsigned=allow_unsigned,
        quiet=quiet,
    )
    shard_frames, shard_fallback_files, shard_payloads_file = _shard_frames_from_args(
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
        output_path=args.output,
        args=args,
        quiet=quiet,
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
    output_path: str | None,
    args: RecoverArgs | None,
    quiet: bool,
) -> RecoveryPlan:
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
    doc_id = _doc_id_from_ciphertext(ciphertext)
    doc_hash = _doc_hash_from_ciphertext(ciphertext)

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
    if shard_frames and passphrase:
        raise ValueError("use either shard inputs or passphrase, not both")
    if shard_frames:
        return _passphrase_from_shard_frames(
            shard_frames,
            expected_doc_id=doc_id,
            expected_doc_hash=doc_hash,
            expected_sign_pub=sign_pub,
            allow_unsigned=allow_unsigned,
        )
    if passphrase:
        return passphrase
    if args is not None:
        return _resolve_recovery_keys(args)
    raise ValueError("passphrase is required for recovery")


def _frames_from_args(
    args: RecoverArgs,
    *,
    qr_payload_encoding: str,
    allow_unsigned: bool,
    quiet: bool,
) -> tuple[list[Frame], str | None, str | None]:
    fallback_file = args.fallback_file
    payloads_file = args.payloads_file
    scan = list(args.scan or [])

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
            raise ValueError(format_fallback_error(exc, context="Recovery text")) from exc
    elif payloads_file:
        input_label = "QR payloads"
        input_detail = payloads_file
        frames = _frames_from_payloads(
            payloads_file,
            "auto",
        )
    elif scan:
        input_label = "Scan"
        input_detail = ", ".join(scan)
        frames = _frames_from_scan(scan, qr_payload_encoding)
    else:
        raise ValueError("either --fallback-file, --payloads-file, or --scan is required")
    return frames, input_label, input_detail


def _extra_auth_frames_from_args(
    args: RecoverArgs,
    *,
    allow_unsigned: bool,
    quiet: bool,
) -> list[Frame]:
    auth_fallback_file = args.auth_fallback_file
    auth_payloads_file = args.auth_payloads_file
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
        extra_auth_frames.extend(_auth_frames_from_payloads(auth_payloads_file, "auto"))
    return extra_auth_frames


def _shard_frames_from_args(
    args: RecoverArgs,
    *,
    quiet: bool,
) -> tuple[list[Frame], list[str], list[str]]:
    shard_fallback_files = list(args.shard_fallback_file or [])
    shard_payloads_file = list(args.shard_payloads_file or [])
    shard_frames: list[Frame] = []
    if shard_fallback_files or shard_payloads_file:
        try:
            shard_frames = _frames_from_shard_inputs(
                shard_fallback_files,
                shard_payloads_file,
                "auto",
            )
        except ValueError as exc:
            raise ValueError(format_fallback_error(exc, context="Shard recovery text")) from exc
        if not shard_frames:
            raise ValueError("no shard payloads found; check shard inputs and try again")
    return shard_frames, shard_fallback_files, shard_payloads_file
