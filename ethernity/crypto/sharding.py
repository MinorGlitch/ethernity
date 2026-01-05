#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import cbor2
from Crypto.Protocol.SecretSharing import Shamir

from .signing import DOC_HASH_LEN, ED25519_PUB_LEN, ED25519_SEED_LEN, ED25519_SIG_LEN, sign_shard
from ..core.validation import require_bytes, require_length

SHARD_VERSION = 3
KEY_TYPE_PASSPHRASE = "passphrase"
BLOCK_SIZE = 16


@dataclass(frozen=True)
class ShardPayload:
    index: int
    threshold: int
    shares: int
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
    if threshold <= 0 or shares <= 0:
        raise ValueError("threshold and shares must be positive")
    if threshold > shares:
        raise ValueError("threshold cannot exceed shares")

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
            shard_index=index,
            share=share_bytes,
            sign_priv=sign_priv,
        )
        payloads.append(
            ShardPayload(
                index=index,
                threshold=threshold,
                shares=shares,
                key_type=KEY_TYPE_PASSPHRASE,
                share=share_bytes,
                secret_len=len(secret),
                doc_hash=doc_hash,
                sign_pub=sign_pub,
                signature=signature,
            )
        )
    return payloads


def recover_passphrase(shares: list[ShardPayload]) -> str:
    if not shares:
        raise ValueError("no shares provided")
    threshold = shares[0].threshold
    key_type = shares[0].key_type
    secret_len = shares[0].secret_len
    share_total = shares[0].shares
    seen_indices: set[int] = set()
    for share in shares:
        if share.key_type != key_type:
            raise ValueError("shard key types do not match")
        if share.threshold != threshold:
            raise ValueError("shard thresholds do not match")
        if share.shares != share_total:
            raise ValueError("shard share counts do not match")
        if share.index in seen_indices:
            raise ValueError("duplicate shard index")
        seen_indices.add(share.index)
        if share.secret_len != secret_len:
            raise ValueError("shard secret lengths do not match")
        if len(share.share) % BLOCK_SIZE != 0:
            raise ValueError("shard share length must be a multiple of block size")
    if len(shares) < threshold:
        raise ValueError(f"need at least {threshold} shard(s) to recover passphrase")

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
        pairs = [(share.index, share.share[start:end]) for share in shares]
        blocks.append(cast(bytes, shamir.combine(pairs)))

    secret = b"".join(blocks)[:secret_len]
    return secret.decode("utf-8")


def encode_shard_payload(payload: ShardPayload) -> bytes:
    data = [
        SHARD_VERSION,
        payload.key_type,
        payload.threshold,
        payload.shares,
        payload.index,
        payload.secret_len,
        payload.share,
        payload.doc_hash,
        payload.sign_pub,
        payload.signature,
    ]
    return cbor2.dumps(data)


def decode_shard_payload(data: bytes) -> ShardPayload:
    decoded = cbor2.loads(data)
    if not isinstance(decoded, (list, tuple)) or len(decoded) < 10:
        raise ValueError("shard payload must be a list")
    version, key_type, threshold, shares, index, secret_len, share, doc_hash, sign_pub, signature = decoded[:10]
    if version != SHARD_VERSION:
        raise ValueError(f"unsupported shard payload version: {version}")
    if key_type != KEY_TYPE_PASSPHRASE:
        raise ValueError(f"unsupported shard key type: {key_type}")
    if not isinstance(threshold, int) or threshold <= 0:
        raise ValueError("shard threshold must be a positive int")
    if not isinstance(shares, int) or shares <= 0:
        raise ValueError("shard shares must be a positive int")
    if not isinstance(index, int) or index <= 0:
        raise ValueError("shard index must be a positive int")
    if not isinstance(secret_len, int) or secret_len <= 0:
        raise ValueError("shard secret length must be a positive int")
    if not isinstance(share, (bytes, bytearray)) or not share:
        raise ValueError("shard share must be bytes")
    doc_hash = require_bytes(doc_hash, DOC_HASH_LEN, label="doc_hash", prefix="shard ")
    sign_pub = require_bytes(sign_pub, ED25519_PUB_LEN, label="sign_pub", prefix="shard ")
    signature = require_bytes(signature, ED25519_SIG_LEN, label="signature", prefix="shard ")
    return ShardPayload(
        index=index,
        threshold=threshold,
        shares=shares,
        key_type=key_type,
        share=bytes(share),
        secret_len=secret_len,
        doc_hash=doc_hash,
        sign_pub=sign_pub,
        signature=signature,
    )
