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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from ethernity.crypto.sharding import (
    KEY_TYPE_PASSPHRASE,
    KEY_TYPE_SIGNING_SEED,
    ShardPayload,
    decode_shard_payload,
    recover_passphrase,
    recover_signing_seed,
    validate_shard_set_consistency,
)
from ethernity.crypto.signing import AuthPayload, decode_auth_payload, verify_auth, verify_shard
from ethernity.encoding.framing import Frame, FrameType

ShardPayloadDecoder = Callable[[bytes], ShardPayload]
ShardVerifier = Callable[..., bool]


@dataclass(frozen=True)
class RecoveryKeyNotice:
    """Non-fatal warning produced while resolving recovery keys."""

    code: str
    message: str
    details: dict[str, object]


RecoveryKeyNoticeSink = Callable[[RecoveryKeyNotice], None]


def resolve_auth_payload(
    auth_frames: list[Frame],
    *,
    doc_id: bytes,
    doc_hash: bytes,
    allow_unsigned: bool,
    require_auth: bool,
    _notice_sink: RecoveryKeyNoticeSink | None = None,
) -> tuple[AuthPayload | None, str]:
    """Validate one AUTH frame without depending on a presentation or logging adapter."""

    if not auth_frames:
        if require_auth:
            raise ValueError("missing auth payload; provide AUTH input to verify recovery")
        if allow_unsigned:
            _notice(
                _notice_sink,
                "AUTH_PAYLOAD_MISSING",
                "no auth payload provided; skipping auth verification",
            )
            return None, "skipped"
        return None, "missing"
    if len(auth_frames) > 1:
        raise ValueError("multiple auth payloads provided")
    frame = auth_frames[0]
    if frame.doc_id != doc_id:
        if allow_unsigned:
            _notice(
                _notice_sink,
                "AUTH_PAYLOAD_INVALID",
                "auth payload doc_id mismatch; verification skipped",
                details={"reason": "doc_id_mismatch"},
            )
            return None, "ignored"
        raise ValueError("auth payload doc_id does not match ciphertext")
    if frame.total != 1 or frame.index != 0:
        raise ValueError("auth payload must be a single-frame payload")
    try:
        payload = decode_auth_payload(frame.data)
    except ValueError as exc:
        if allow_unsigned:
            _notice(
                _notice_sink,
                "AUTH_PAYLOAD_INVALID",
                f"invalid auth payload; verification skipped: {exc}",
                details={"reason": str(exc)},
            )
            return None, "invalid"
        raise
    if not hmac.compare_digest(payload.doc_hash, doc_hash):
        if allow_unsigned:
            _notice(
                _notice_sink,
                "AUTH_DOC_HASH_MISMATCH",
                "auth doc_hash mismatch; verification skipped",
            )
            return None, "ignored"
        raise ValueError("auth doc_hash does not match ciphertext")
    if not verify_auth(doc_hash, sign_pub=payload.sign_pub, signature=payload.signature):
        if allow_unsigned:
            _notice(
                _notice_sink,
                "AUTH_SIGNATURE_INVALID",
                "auth signature verification failed; verification skipped",
            )
            return None, "ignored"
        raise ValueError("invalid auth signature")
    return payload, "verified"


def _notice(
    sink: RecoveryKeyNoticeSink | None,
    code: str,
    message: str,
    *,
    details: Mapping[str, object] | None = None,
) -> None:
    if sink is not None:
        sink(RecoveryKeyNotice(code=code, message=message, details=dict(details or {})))


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

    return _validated_shard_payloads_from_frames(
        frames,
        expected_doc_id=expected_doc_id,
        expected_doc_hash=expected_doc_hash,
        expected_sign_pub=expected_sign_pub,
        allow_unsigned=allow_unsigned,
        key_type=key_type,
        secret_label=secret_label,
        payload_decoder=decode_shard_payload,
        shard_verifier=verify_shard,
    )


def _validated_shard_payloads_from_frames(
    frames: Sequence[Frame],
    *,
    expected_doc_id: bytes | None,
    expected_doc_hash: bytes | None,
    expected_sign_pub: bytes | None,
    allow_unsigned: bool,
    key_type: str,
    secret_label: str,
    payload_decoder: ShardPayloadDecoder,
    shard_verifier: ShardVerifier,
) -> list[ShardPayload]:
    """Dependency-injected implementation used by compatibility adapters."""

    shares: dict[int, ShardPayload] = {}
    doc_hash: bytes | None = expected_doc_hash
    sign_pub: bytes | None = expected_sign_pub
    for frame in frames:
        if frame.frame_type != FrameType.KEY_DOCUMENT:
            raise ValueError("shard payloads must be KEY_DOCUMENT type")
        if expected_doc_id is not None and frame.doc_id != expected_doc_id:
            raise ValueError("shard payload doc_id does not match ciphertext")
        if frame.total != 1 or frame.index != 0:
            raise ValueError("shard payloads must be single-frame payloads")
        payload = payload_decoder(frame.data)
        if payload.key_type != key_type:
            raise ValueError(f"shard payloads must be {secret_label} shards")
        if doc_hash is None:
            doc_hash = payload.doc_hash
        elif not hmac.compare_digest(payload.doc_hash, doc_hash):
            raise ValueError("shard doc_hash does not match")
        if sign_pub is None:
            sign_pub = payload.sign_pub
        elif not hmac.compare_digest(payload.sign_pub, sign_pub):
            raise ValueError("shard signing key does not match")
        if not allow_unsigned and not shard_verifier(
            doc_hash,
            shard_version=payload.version,
            key_type=payload.key_type,
            threshold=payload.threshold,
            share_count=payload.share_count,
            share_index=payload.share_index,
            secret_len=payload.secret_len,
            share=payload.share,
            shard_set_id=payload.shard_set_id,
            sign_pub=payload.sign_pub,
            signature=payload.signature,
        ):
            raise ValueError("invalid shard signature")
        existing = shares.get(payload.share_index)
        if existing is not None:
            if existing != payload:
                raise ValueError("duplicate shard index with mismatched data")
            continue
        shares[payload.share_index] = payload

    share_list = list(shares.values())
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
    if len(share_list) < threshold:
        raise InsufficientShardError(
            threshold=threshold,
            provided_count=len(share_list),
            secret_label=secret_label,
            share_count=share_total,
            shard_version=share_list[0].version,
        )

    return share_list


__all__ = [
    "InsufficientShardError",
    "RecoveryKeyNotice",
    "RecoveryKeyNoticeSink",
    "passphrase_from_shard_frames",
    "resolve_auth_payload",
    "signing_seed_from_shard_frames",
    "validated_shard_payloads_from_frames",
]
