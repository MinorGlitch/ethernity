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

from __future__ import annotations

from ...crypto.sharding import SHARD_VERSION, ShardPayload, decode_shard_payload, recover_passphrase
from ...crypto.signing import decode_auth_payload, verify_auth, verify_shard
from ...encoding.framing import Frame, FrameType
from ..core.log import _warn
from ..core.types import RecoverArgs


def _resolve_recovery_keys(args: RecoverArgs) -> str:
    if args.passphrase:
        return args.passphrase
    raise ValueError("passphrase is required for recovery")


def _resolve_auth_payload(
    auth_frames: list[Frame],
    *,
    doc_id: bytes,
    doc_hash: bytes,
    allow_unsigned: bool,
    require_auth: bool,
    quiet: bool,
):
    if not auth_frames:
        if require_auth:
            raise ValueError("missing auth payload; use --skip-auth-check to skip verification")
        if allow_unsigned:
            _warn("no auth payload provided; skipping auth verification", quiet=quiet)
            return None, "skipped"
        return None, "missing"
    if len(auth_frames) > 1:
        raise ValueError("multiple auth payloads provided")
    frame = auth_frames[0]
    if frame.doc_id != doc_id:
        raise ValueError("auth payload doc_id does not match ciphertext")
    if frame.total != 1 or frame.index != 0:
        raise ValueError("auth payload must be a single-frame payload")
    try:
        payload = decode_auth_payload(frame.data)
    except ValueError as exc:
        if allow_unsigned:
            _warn(f"invalid auth payload; verification skipped: {exc}", quiet=quiet)
            return None, "invalid"
        raise
    if payload.doc_hash != doc_hash:
        if allow_unsigned:
            _warn("auth doc_hash mismatch; verification skipped", quiet=quiet)
            return None, "ignored"
        raise ValueError("auth doc_hash does not match ciphertext")
    if not verify_auth(doc_hash, sign_pub=payload.sign_pub, signature=payload.signature):
        if allow_unsigned:
            _warn("auth signature verification failed; verification skipped", quiet=quiet)
            return None, "ignored"
        raise ValueError("invalid auth signature")
    return payload, "verified"


def _passphrase_from_shard_frames(
    frames: list[Frame],
    *,
    expected_doc_id: bytes | None,
    expected_doc_hash: bytes | None,
    expected_sign_pub: bytes | None,
    allow_unsigned: bool,
) -> str:
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
        payload = decode_shard_payload(frame.data)
        if doc_hash is None:
            doc_hash = payload.doc_hash
        elif payload.doc_hash != doc_hash:
            raise ValueError("shard doc_hash does not match")
        if sign_pub is None:
            sign_pub = payload.sign_pub
        elif payload.sign_pub != sign_pub:
            raise ValueError("shard signing key does not match")
        if not allow_unsigned and not verify_shard(
            doc_hash,
            shard_version=SHARD_VERSION,
            key_type=payload.key_type,
            threshold=payload.threshold,
            share_count=payload.share_count,
            share_index=payload.share_index,
            secret_len=payload.secret_len,
            share=payload.share,
            sign_pub=payload.sign_pub,
            signature=payload.signature,
        ):
            raise ValueError("invalid shard signature")
        existing = shares.get(payload.share_index)
        if existing is not None:
            if existing.share != payload.share:
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
    if len(share_list) < threshold:
        raise ValueError(f"need at least {threshold} shard(s) to recover passphrase")

    return recover_passphrase(share_list)
