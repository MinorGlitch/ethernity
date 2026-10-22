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

"""Adapter-neutral recovery-key reconstruction from validated shard frames."""

from __future__ import annotations

import hmac
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TypedDict

from ethernity.crypto.sharding import (
    KEY_TYPE_PASSPHRASE,
    KEY_TYPE_SIGNING_SEED,
    ShardPayload,
    decode_shard_payload,
    recover_passphrase,
    recover_signing_seed,
    validate_shard_set_consistency,
    verify_shard_payload,
)
from ethernity.crypto.signing import AuthPayload, decode_auth_payload, verify_auth, verify_shard
from ethernity.encoding.framing import Frame, FrameType
from ethernity.workflows.shared import issue_codes
from ethernity.workflows.shared.notices import WorkflowNoticeSink, send_notice


@dataclass(frozen=True)
class DecodedShard:
    """A carrier and its parsed payload; authentication is a separate check."""

    frame: Frame
    payload: ShardPayload

    @classmethod
    def decode(cls, frame: Frame) -> DecodedShard:
        return cls(frame, decode_shard_payload(frame.data))


class AuthVerificationOptions(TypedDict):
    doc_id: bytes
    doc_hash: bytes
    allow_unsigned: bool
    require_auth: bool


@dataclass(frozen=True)
class RecoveryTrust:
    """Document identity and signature policy carried through recovery validation."""

    doc_id: bytes
    doc_hash: bytes
    sign_pub: bytes | None = None
    allow_unsigned: bool = False

    def auth_options(self, *, require_auth: bool) -> AuthVerificationOptions:
        return AuthVerificationOptions(
            doc_id=self.doc_id,
            doc_hash=self.doc_hash,
            allow_unsigned=self.allow_unsigned,
            require_auth=require_auth,
        )

    def validated_shards(
        self, frames: Sequence[Frame], *, key_type: str, secret_label: str
    ) -> list[ShardPayload]:
        return validated_shard_payloads_from_frames(
            frames,
            expected_doc_id=self.doc_id,
            expected_doc_hash=self.doc_hash,
            expected_sign_pub=self.sign_pub,
            allow_unsigned=self.allow_unsigned,
            key_type=key_type,
            secret_label=secret_label,
        )


class AuthValidationError(ValueError):
    """AUTH failure shared by execution and best-effort inspection."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: str = "invalid",
        inspection_message: str | None = None,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.issue_code = code
        self.status = status
        self.inspection_message = inspection_message or message
        self.details = dict(details or {})


def resolve_auth_payload(
    auth_frames: list[Frame],
    *,
    doc_id: bytes,
    doc_hash: bytes,
    allow_unsigned: bool,
    require_auth: bool,
    _notice_sink: WorkflowNoticeSink | None = None,
) -> tuple[AuthPayload | None, str]:
    """Validate one AUTH frame without depending on a presentation or logging adapter."""

    if not auth_frames:
        if require_auth:
            raise AuthValidationError(
                issue_codes.AUTH_PAYLOAD_MISSING,
                "missing auth payload; provide AUTH input to verify recovery",
                status="missing",
                inspection_message="missing AUTH payload; provide AUTH input to check readiness",
            )
        if allow_unsigned:
            send_notice(
                _notice_sink,
                issue_codes.AUTH_PAYLOAD_MISSING,
                "no auth payload provided; skipping auth verification",
            )
            return None, "skipped"
        return None, "missing"
    if len(auth_frames) > 1:
        raise AuthValidationError(
            issue_codes.AUTH_PAYLOAD_MULTIPLE, "multiple auth payloads provided"
        )
    frame = auth_frames[0]
    if frame.doc_id != doc_id:
        if allow_unsigned:
            send_notice(
                _notice_sink,
                issue_codes.AUTH_PAYLOAD_INVALID,
                "auth payload doc_id mismatch; verification skipped",
                details={"reason": "doc_id_mismatch"},
            )
            return None, "ignored"
        raise AuthValidationError(
            issue_codes.AUTH_PAYLOAD_DOC_ID_MISMATCH,
            "auth payload doc_id does not match ciphertext",
        )
    if frame.total != 1 or frame.index != 0:
        raise AuthValidationError(
            issue_codes.AUTH_PAYLOAD_FRAME_INVALID, "auth payload must be a single-frame payload"
        )
    return _decode_and_verify_auth_payload(
        frame, doc_hash=doc_hash, allow_unsigned=allow_unsigned, notice_sink=_notice_sink
    )


def _decode_and_verify_auth_payload(
    frame: Frame,
    *,
    doc_hash: bytes,
    allow_unsigned: bool,
    notice_sink: WorkflowNoticeSink | None,
) -> tuple[AuthPayload | None, str]:
    try:
        payload = decode_auth_payload(frame.data)
    except ValueError as exc:
        if allow_unsigned:
            send_notice(
                notice_sink,
                issue_codes.AUTH_PAYLOAD_INVALID,
                f"invalid auth payload; verification skipped: {exc}",
                details={"reason": str(exc)},
            )
            return None, "invalid"
        raise AuthValidationError(
            issue_codes.AUTH_PAYLOAD_INVALID,
            str(exc),
            inspection_message=f"invalid auth payload: {exc}",
            details={"reason": str(exc)},
        ) from exc
    if not hmac.compare_digest(payload.doc_hash, doc_hash):
        if allow_unsigned:
            send_notice(
                notice_sink,
                issue_codes.AUTH_DOC_HASH_MISMATCH,
                "auth doc_hash mismatch; verification skipped",
            )
            return None, "ignored"
        raise AuthValidationError(
            issue_codes.AUTH_DOC_HASH_MISMATCH,
            "auth doc_hash does not match ciphertext",
            status="ignored",
        )
    if not verify_auth(doc_hash, sign_pub=payload.sign_pub, signature=payload.signature):
        if allow_unsigned:
            send_notice(
                notice_sink,
                issue_codes.AUTH_SIGNATURE_INVALID,
                "auth signature verification failed; verification skipped",
            )
            return None, "ignored"
        raise AuthValidationError(
            issue_codes.AUTH_SIGNATURE_INVALID, "invalid auth signature", status="ignored"
        )
    return payload, "verified"


class InsufficientShardError(ValueError):
    """Raised when a shard set is well-formed but under quorum."""

    def __init__(
        self,
        *,
        threshold: int,
        provided_count: int,
        secret_label: str,
        share_count: int | None = None,
        shard_version: int | None = None,
    ) -> None:
        self.threshold = threshold
        self.provided_count = provided_count
        self.secret_label = secret_label
        self.share_count = share_count
        self.shard_version = shard_version
        super().__init__(f"need at least {threshold} shard(s) to recover {secret_label}")


def passphrase_from_shard_frames(
    frames: Sequence[Frame],
    *,
    expected_doc_id: bytes | None,
    expected_doc_hash: bytes | None,
    expected_sign_pub: bytes | None,
    allow_unsigned: bool,
) -> str:
    """Recover a passphrase from a validated quorum of passphrase shard frames."""

    share_list = validated_shard_payloads_from_frames(
        frames,
        expected_doc_id=expected_doc_id,
        expected_doc_hash=expected_doc_hash,
        expected_sign_pub=expected_sign_pub,
        allow_unsigned=allow_unsigned,
        key_type=KEY_TYPE_PASSPHRASE,
        secret_label="passphrase",
    )
    return recover_passphrase(share_list, verify_signatures=False)


def signing_seed_from_shard_frames(
    frames: Sequence[Frame],
    *,
    expected_doc_id: bytes | None,
    expected_doc_hash: bytes | None,
    expected_sign_pub: bytes | None,
    allow_unsigned: bool,
) -> bytes:
    """Recover a signing seed from a validated quorum of signing-key shard frames."""

    share_list = validated_shard_payloads_from_frames(
        frames,
        expected_doc_id=expected_doc_id,
        expected_doc_hash=expected_doc_hash,
        expected_sign_pub=expected_sign_pub,
        allow_unsigned=allow_unsigned,
        key_type=KEY_TYPE_SIGNING_SEED,
        secret_label="signing key",
    )
    return recover_signing_seed(share_list, verify_signatures=False)


def validated_shard_payloads_from_frames(
    frames: Sequence[Frame],
    *,
    expected_doc_id: bytes | None,
    expected_doc_hash: bytes | None,
    expected_sign_pub: bytes | None,
    allow_unsigned: bool,
    key_type: str,
    secret_label: str,
) -> list[ShardPayload]:
    """Validate and deduplicate one shard set, requiring a complete quorum."""

    decoded = []
    for frame in frames:
        _validate_shard_frame(frame, expected_doc_id)
        decoded.append(DecodedShard.decode(frame))
    return [
        item.payload
        for item in validate_decoded_shards(
            decoded,
            expected_doc_id=expected_doc_id,
            expected_doc_hash=expected_doc_hash,
            expected_sign_pub=expected_sign_pub,
            allow_unsigned=allow_unsigned,
            key_type=key_type,
            secret_label=secret_label,
        )
    ]


def validate_decoded_shards(
    decoded: Sequence[DecodedShard],
    *,
    expected_doc_id: bytes | None,
    expected_doc_hash: bytes | None,
    expected_sign_pub: bytes | None,
    allow_unsigned: bool = False,
    key_type: str,
    secret_label: str,
    require_quorum: bool = True,
) -> tuple[DecodedShard, ...]:
    """Bind, authenticate and deduplicate parsed sheets before using their values."""
    shares: dict[int, DecodedShard] = {}
    doc_hash, sign_pub = expected_doc_hash, expected_sign_pub
    for item in decoded:
        frame, payload = item.frame, item.payload
        _validate_shard_frame(frame, expected_doc_id)
        if payload.key_type != key_type:
            raise ValueError(f"shard payloads must be {secret_label} shards")
        doc_hash, sign_pub = _bind_shard_identity(payload, doc_hash=doc_hash, sign_pub=sign_pub)
        existing = shares.get(payload.share_index)
        if existing is not None:
            if existing.payload != payload:
                raise ValueError("duplicate shard index with mismatched data")
            continue
        if not allow_unsigned and not verify_shard_payload(payload, verifier=verify_shard):
            raise ValueError("invalid shard signature")
        shares[payload.share_index] = item

    result = tuple(shares.values())
    payloads = [item.payload for item in result]
    _require_shard_quorum(payloads, secret_label=secret_label, require_quorum=require_quorum)
    return result


def _validate_shard_frame(frame: Frame, expected_doc_id: bytes | None) -> None:
    if frame.frame_type != FrameType.KEY_DOCUMENT:
        raise ValueError("shard payloads must be KEY_DOCUMENT type")
    if expected_doc_id is not None and frame.doc_id != expected_doc_id:
        raise ValueError("shard payload doc_id does not match ciphertext")
    if frame.total != 1 or frame.index != 0:
        raise ValueError("shard payloads must be single-frame payloads")


def _bind_shard_identity(
    payload: ShardPayload,
    *,
    doc_hash: bytes | None,
    sign_pub: bytes | None,
) -> tuple[bytes, bytes]:
    if doc_hash is not None and not hmac.compare_digest(payload.doc_hash, doc_hash):
        raise ValueError("shard doc_hash does not match")
    if sign_pub is not None and not hmac.compare_digest(payload.sign_pub, sign_pub):
        raise ValueError("shard signing key does not match")
    return payload.doc_hash, payload.sign_pub


def _require_shard_quorum(
    share_list: list[ShardPayload], *, secret_label: str, require_quorum: bool
) -> None:
    if not share_list:
        raise ValueError("no shard payloads provided")

    threshold = share_list[0].threshold
    share_total = share_list[0].share_count
    for share in share_list:
        if share.threshold != threshold:
            raise ValueError("shard thresholds do not match")
        if share.share_count != share_total:
            raise ValueError("shard share counts do not match")
    validate_shard_set_consistency(share_list, verify_signatures=False)
    if require_quorum and len(share_list) < threshold:
        raise InsufficientShardError(
            threshold=threshold,
            provided_count=len(share_list),
            secret_label=secret_label,
            share_count=share_total,
            shard_version=share_list[0].version,
        )


__all__ = [
    "AuthValidationError",
    "DecodedShard",
    "validate_decoded_shards",
    "InsufficientShardError",
    "RecoveryTrust",
    "passphrase_from_shard_frames",
    "resolve_auth_payload",
    "signing_seed_from_shard_frames",
    "validated_shard_payloads_from_frames",
]
