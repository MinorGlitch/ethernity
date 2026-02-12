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

from dataclasses import dataclass
from typing import Any, cast

from Crypto.Protocol.SecretSharing import Shamir

from ..core.validation import require_bytes, require_dict, require_keys, require_length
from ..encoding.cbor import dumps_canonical, loads_canonical
from .signing import DOC_HASH_LEN, ED25519_PUB_LEN, ED25519_SEED_LEN, ED25519_SIG_LEN, sign_shard

SHARD_VERSION = 1
KEY_TYPE_PASSPHRASE = "passphrase"
KEY_TYPE_SIGNING_SEED = "signing-seed"
BLOCK_SIZE = 16
MAX_SHARES = 255


@dataclass(frozen=True)
class ShardPayload:
    share_index: int
    threshold: int
    share_count: int
    key_type: str
    share: bytes
    secret_len: int
    doc_hash: bytes
    sign_pub: bytes
    signature: bytes


def split_passphrase(
    passphrase: str,
    *,
    threshold: int,
    shares: int,
    doc_hash: bytes,
    sign_priv: bytes,
    sign_pub: bytes,
) -> list[ShardPayload]:
    secret = passphrase.encode("utf-8")
    if not secret:
        raise ValueError("passphrase cannot be empty")
    return _split_secret(
        secret,
        threshold=threshold,
        shares=shares,
        doc_hash=doc_hash,
        sign_priv=sign_priv,
        sign_pub=sign_pub,
        key_type=KEY_TYPE_PASSPHRASE,
    )


def split_signing_seed(
    seed: bytes,
    *,
    threshold: int,
    shares: int,
    doc_hash: bytes,
    sign_priv: bytes,
    sign_pub: bytes,
) -> list[ShardPayload]:
    if not seed:
        raise ValueError("signing seed cannot be empty")
    return _split_secret(
        seed,
        threshold=threshold,
        shares=shares,
        doc_hash=doc_hash,
        sign_priv=sign_priv,
        sign_pub=sign_pub,
        key_type=KEY_TYPE_SIGNING_SEED,
    )


def recover_passphrase(shares: list[ShardPayload]) -> str:
    secret = _recover_secret(shares, key_type=KEY_TYPE_PASSPHRASE)
    return secret.decode("utf-8")


def recover_signing_seed(shares: list[ShardPayload]) -> bytes:
    return _recover_secret(shares, key_type=KEY_TYPE_SIGNING_SEED)


def encode_shard_payload(payload: ShardPayload) -> bytes:
    data = {
        "version": SHARD_VERSION,
        "type": payload.key_type,
        "threshold": payload.threshold,
        "share_count": payload.share_count,
        "share_index": payload.share_index,
        "length": payload.secret_len,
        "share": payload.share,
        "hash": payload.doc_hash,
        "pub": payload.sign_pub,
        "sig": payload.signature,
    }
    return dumps_canonical(data)


def decode_shard_payload(data: bytes) -> ShardPayload:
    decoded = require_dict(loads_canonical(data, label="shard payload"), label="shard payload")
    require_keys(
        decoded,
        (
            "version",
            "type",
            "threshold",
            "share_count",
            "share_index",
            "length",
            "share",
            "hash",
            "pub",
            "sig",
        ),
        label="shard payload",
    )
    version = decoded["version"]
    key_type = decoded["type"]
    threshold = decoded["threshold"]
    share_count = decoded["share_count"]
    share_index = decoded["share_index"]
    secret_len = decoded["length"]
    share = decoded["share"]
    doc_hash = decoded["hash"]
    sign_pub = decoded["pub"]
    signature = decoded["sig"]
    if version != SHARD_VERSION:
        raise ValueError(f"unsupported shard payload version: {version}")
    if key_type not in (KEY_TYPE_PASSPHRASE, KEY_TYPE_SIGNING_SEED):
        raise ValueError(f"unsupported shard key type: {key_type}")
    if not isinstance(threshold, int) or threshold <= 0:
        raise ValueError("shard threshold must be a positive int")
    if threshold > MAX_SHARES:
        raise ValueError(f"shard threshold must be <= {MAX_SHARES}")
    if not isinstance(share_count, int) or share_count <= 0:
        raise ValueError("shard share_count must be a positive int")
    if share_count > MAX_SHARES:
        raise ValueError(f"shard share_count must be <= {MAX_SHARES}")
    if not isinstance(share_index, int) or share_index <= 0:
        raise ValueError("shard share_index must be a positive int")
    if share_index > MAX_SHARES:
        raise ValueError(f"shard share_index must be <= {MAX_SHARES}")
    if threshold > share_count:
        raise ValueError("shard threshold cannot exceed share_count")
    if share_index > share_count:
        raise ValueError("shard share_index cannot exceed share_count")
    if not isinstance(secret_len, int) or secret_len <= 0:
        raise ValueError("shard length must be a positive int")
    if not isinstance(share, (bytes, bytearray)) or not share:
        raise ValueError("shard share must be bytes")
    if len(share) % BLOCK_SIZE != 0:
        raise ValueError("shard share length must be a multiple of block size")
    if secret_len > len(share):
        raise ValueError("shard length cannot exceed share length")
    expected_len = ((secret_len + BLOCK_SIZE - 1) // BLOCK_SIZE) * BLOCK_SIZE
    if len(share) != expected_len:
        raise ValueError("shard share length does not match secret length")
    doc_hash = require_bytes(doc_hash, DOC_HASH_LEN, label="hash", prefix="shard ")
    sign_pub = require_bytes(sign_pub, ED25519_PUB_LEN, label="pub", prefix="shard ")
    signature = require_bytes(signature, ED25519_SIG_LEN, label="sig", prefix="shard ")
    return ShardPayload(
        share_index=share_index,
        threshold=threshold,
        share_count=share_count,
        key_type=key_type,
        share=bytes(share),
        secret_len=secret_len,
        doc_hash=doc_hash,
        sign_pub=sign_pub,
        signature=signature,
    )


def _split_secret(
    secret: bytes,
    *,
    threshold: int,
    shares: int,
    doc_hash: bytes,
    sign_priv: bytes,
    sign_pub: bytes,
    key_type: str,
) -> list[ShardPayload]:
    if threshold <= 0 or shares <= 0:
        raise ValueError("threshold and shares must be positive")
    if threshold > shares:
        raise ValueError("threshold cannot exceed shares")
    if threshold > MAX_SHARES or shares > MAX_SHARES:
        raise ValueError(f"threshold and shares must be <= {MAX_SHARES}")

    blocks: list[bytes] = []
    for offset in range(0, len(secret), BLOCK_SIZE):
        block = secret[offset : offset + BLOCK_SIZE]
        if len(block) < BLOCK_SIZE:
            block = block.ljust(BLOCK_SIZE, b"\x00")
        blocks.append(block)

    share_map: dict[int, bytearray] = {}
    shamir = cast(Any, Shamir)
    for block in blocks:
        split = shamir.split(threshold, shares, block)
        for index, share in split:
            bucket = share_map.setdefault(index, bytearray())
            bucket.extend(share)

    require_length(doc_hash, DOC_HASH_LEN, label="doc_hash", prefix="shard ")
    require_length(sign_pub, ED25519_PUB_LEN, label="sign_pub", prefix="shard ")
    require_length(sign_priv, ED25519_SEED_LEN, label="sign_priv", prefix="shard ")

    payloads = []
    for index, share in share_map.items():
        share_bytes = bytes(share)
        signature = sign_shard(
            doc_hash,
            shard_version=SHARD_VERSION,
            key_type=key_type,
            threshold=threshold,
            share_count=shares,
            share_index=index,
            secret_len=len(secret),
            share=share_bytes,
            sign_pub=sign_pub,
            sign_priv=sign_priv,
        )
        payloads.append(
            ShardPayload(
                share_index=index,
                threshold=threshold,
                share_count=shares,
                key_type=key_type,
                share=share_bytes,
                secret_len=len(secret),
                doc_hash=doc_hash,
                sign_pub=sign_pub,
                signature=signature,
            )
        )
    return payloads


def _recover_secret(shares: list[ShardPayload], *, key_type: str) -> bytes:
    if not shares:
        raise ValueError("no shares provided")
    threshold = shares[0].threshold
    secret_len = shares[0].secret_len
    share_total = shares[0].share_count
    seen_indices: set[int] = set()
    for share in shares:
        if share.key_type != key_type:
            raise ValueError("shard key types do not match")
        if share.threshold != threshold:
            raise ValueError("shard thresholds do not match")
        if share.share_count != share_total:
            raise ValueError("shard share counts do not match")
        if share.share_index in seen_indices:
            raise ValueError("duplicate shard index")
        seen_indices.add(share.share_index)
        if share.secret_len != secret_len:
            raise ValueError("shard secret lengths do not match")
        if len(share.share) % BLOCK_SIZE != 0:
            raise ValueError("shard share length must be a multiple of block size")
    if len(shares) < threshold:
        raise ValueError(f"need at least {threshold} shard(s) to recover secret")

    block_count = (secret_len + BLOCK_SIZE - 1) // BLOCK_SIZE
    expected_len = block_count * BLOCK_SIZE
    for share in shares:
        if len(share.share) != expected_len:
            raise ValueError("shard share length does not match secret length")

    shamir = cast(Any, Shamir)
    blocks: list[bytes] = []
    for block_idx in range(block_count):
        start = block_idx * BLOCK_SIZE
        end = start + BLOCK_SIZE
        pairs = [(share.share_index, share.share[start:end]) for share in shares]
        blocks.append(cast(bytes, shamir.combine(pairs)))

    return b"".join(blocks)[:secret_len]
