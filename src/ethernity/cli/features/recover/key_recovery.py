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

from ethernity.cli.shared.log import warn
from ethernity.cli.shared.types import RecoverArgs
from ethernity.crypto.sharding import (
    KEY_TYPE_PASSPHRASE,
    KEY_TYPE_SIGNING_SEED,
    ShardPayload,
    decode_shard_payload,
    recover_passphrase,
    recover_signing_seed,
)
from ethernity.crypto.signing import verify_shard
from ethernity.encoding.framing import Frame
from ethernity.workflows.recovery.keys import (
    InsufficientShardError,
    RecoveryKeyNotice,
    _validated_shard_payloads_from_frames,
    resolve_auth_payload as _resolve_auth_payload,
)

__all__ = [
    "InsufficientShardError",
    "passphrase_from_shard_frames",
    "resolve_auth_payload",
    "resolve_recovery_keys",
    "signing_seed_from_shard_frames",
    "validated_shard_payloads_from_frames",
]


def resolve_recovery_keys(args: RecoverArgs) -> str:
    if args.passphrase:
        return args.passphrase
    raise ValueError("passphrase is required for recovery")


def resolve_auth_payload(
    auth_frames: list[Frame],
    *,
    doc_id: bytes,
    doc_hash: bytes,
    allow_unsigned: bool,
    require_auth: bool,
    quiet: bool,
):
    return _resolve_auth_payload(
        auth_frames,
        doc_id=doc_id,
        doc_hash=doc_hash,
        allow_unsigned=allow_unsigned,
        require_auth=require_auth,
        _notice_sink=lambda notice: _warn_notice(notice, quiet=quiet),
    )


def _warn_notice(notice: RecoveryKeyNotice, *, quiet: bool) -> None:
    warn(notice.message, quiet=quiet, code=notice.code, details=notice.details)


def passphrase_from_shard_frames(
    frames: list[Frame],
    *,
    expected_doc_id: bytes | None,
    expected_doc_hash: bytes | None,
    expected_sign_pub: bytes | None,
    allow_unsigned: bool,
) -> str:
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
    frames: list[Frame],
    *,
    expected_doc_id: bytes | None,
    expected_doc_hash: bytes | None,
    expected_sign_pub: bytes | None,
    allow_unsigned: bool,
) -> bytes:
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
    frames: list[Frame],
    *,
    expected_doc_id: bytes | None,
    expected_doc_hash: bytes | None,
    expected_sign_pub: bytes | None,
    allow_unsigned: bool,
    key_type: str,
    secret_label: str,
) -> list[ShardPayload]:
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
