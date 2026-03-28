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

"""Shamir-based shard payload encoding, decoding, split, and recovery helpers."""

from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass

from Crypto.Protocol.SecretSharing import Shamir

from ethernity.core.validation import (
    require_bytes,
    require_dict,
    require_int,
    require_keys,
    require_length,
    require_positive_int,
)
from ethernity.crypto._shamir_compat import BLOCK_SIZE, interpolate_share_blocks
from ethernity.crypto.signing import (
    DOC_HASH_LEN,
    ED25519_PUB_LEN,
    ED25519_SEED_LEN,
    ED25519_SIG_LEN,
    SHARD_SET_ID_LEN,
    derive_public_key,
    sign_shard,
    verify_shard,
)
from ethernity.encoding.cbor import dumps_canonical, loads_canonical

LEGACY_SHARD_VERSION = 1
SHARD_VERSION = 2
KEY_TYPE_PASSPHRASE = "passphrase"
KEY_TYPE_SIGNING_SEED = "signing-seed"
MAX_SHARES = 255
_INCOMPATIBLE_SHARD_SET_MESSAGE = (
    "shards are not mutually compatible; they may come from different shard sets"
)


@dataclass(frozen=True)
class ShardPayload:
    """Signed shard payload metadata and share bytes."""

    share_index: int
    threshold: int
    share_count: int
    key_type: str
    share: bytes
    secret_len: int
    doc_hash: bytes
    sign_pub: bytes
    signature: bytes
    version: int = SHARD_VERSION
    shard_set_id: bytes | None = None


def split_passphrase(
    passphrase: str,
    *,
    threshold: int,
    shares: int,
    doc_hash: bytes,
    sign_priv: bytes,
    sign_pub: bytes,
) -> list[ShardPayload]:
    """Split a passphrase into signed shard payloads."""

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
    """Split an Ed25519 signing seed into signed shard payloads."""

    if len(seed) != ED25519_SEED_LEN:
        raise ValueError(f"signing seed must be {ED25519_SEED_LEN} bytes")
    return _split_secret(
        seed,
        threshold=threshold,
        shares=shares,
        doc_hash=doc_hash,
        sign_priv=sign_priv,
        sign_pub=sign_pub,
        key_type=KEY_TYPE_SIGNING_SEED,
    )


def recover_passphrase(
    shares: list[ShardPayload],
    *,
    verify_signatures: bool = True,
) -> str:
    """Recover a UTF-8 passphrase from shard payloads."""

    secret = _recover_secret(
        shares,
        key_type=KEY_TYPE_PASSPHRASE,
        verify_signatures=verify_signatures,
    )
    return secret.decode("utf-8")


def recover_signing_seed(
    shares: list[ShardPayload],
    *,
    verify_signatures: bool = True,
) -> bytes:
    """Recover an Ed25519 signing seed from shard payloads."""

    seed = _recover_secret(
        shares,
        key_type=KEY_TYPE_SIGNING_SEED,
        verify_signatures=verify_signatures,
    )
    if len(seed) != ED25519_SEED_LEN:
        raise ValueError(f"signing seed must be {ED25519_SEED_LEN} bytes")
    return seed


def mint_replacement_shards(
    shares: list[ShardPayload],
    *,
    count: int,
    sign_priv: bytes,
) -> list[ShardPayload]:
    """Mint replacement shards compatible with an existing shard set."""

    if not shares:
        raise ValueError("no shares provided")
    count = require_positive_int(count, label="replacement shard count")
    threshold = shares[0].threshold
    secret_len = shares[0].secret_len
    share_total = shares[0].share_count
    key_type = shares[0].key_type
    doc_hash = shares[0].doc_hash
    source_sign_pub = shares[0].sign_pub
    version = shares[0].version
    shard_set_id = shares[0].shard_set_id
    seen_indices: set[int] = set()
    for share in shares:
        if share.key_type != key_type:
            raise ValueError("shard key types do not match")
        if share.threshold != threshold:
            raise ValueError("shard thresholds do not match")
        if share.share_count != share_total:
            raise ValueError("shard share counts do not match")
        if share.secret_len != secret_len:
            raise ValueError("shard secret lengths do not match")
        if share.doc_hash != doc_hash:
            raise ValueError("shard doc hashes do not match")
        if not hmac.compare_digest(share.sign_pub, source_sign_pub):
            raise ValueError("shard signing keys do not match")
        if share.share_index in seen_indices:
            raise ValueError("duplicate shard index")
        seen_indices.add(share.share_index)
    validate_shard_set_consistency(shares)
    if len(shares) < threshold:
        raise ValueError(f"need at least {threshold} shard(s) to mint compatible replacements")

    missing_indices = [index for index in range(1, share_total + 1) if index not in seen_indices]
    if count > len(missing_indices):
        raise ValueError(
            f"only {len(missing_indices)} replacement shard(s) can be minted from this set"
        )

    source_shares = sorted(shares, key=lambda item: item.share_index)[:threshold]
    block_count = (secret_len + BLOCK_SIZE - 1) // BLOCK_SIZE
    require_length(doc_hash, DOC_HASH_LEN, label="doc_hash", prefix="shard ")
    require_length(sign_priv, ED25519_SEED_LEN, label="sign_priv", prefix="shard ")
    replacement_sign_pub = derive_public_key(sign_priv)
    if not hmac.compare_digest(replacement_sign_pub, source_sign_pub):
        raise ValueError("replacement signing key must match source shard set")

    payloads: list[ShardPayload] = []
    for share_index in missing_indices[:count]:
        share_bytes = interpolate_share_blocks(
            [(share.share_index, share.share) for share in source_shares],
            target_index=share_index,
            block_count=block_count,
        )
        signature = sign_shard(
            doc_hash,
            shard_version=version,
            key_type=key_type,
            threshold=threshold,
            share_count=share_total,
            share_index=share_index,
            secret_len=secret_len,
            share=share_bytes,
            shard_set_id=shard_set_id,
            sign_pub=replacement_sign_pub,
            sign_priv=sign_priv,
        )
        payloads.append(
            ShardPayload(
                share_index=share_index,
                threshold=threshold,
                share_count=share_total,
                key_type=key_type,
                share=share_bytes,
                secret_len=secret_len,
                doc_hash=doc_hash,
                sign_pub=replacement_sign_pub,
                signature=signature,
                version=version,
                shard_set_id=shard_set_id,
            )
        )
    return payloads


def encode_shard_payload(payload: ShardPayload) -> bytes:
    """Encode a shard payload as canonical CBOR."""

    (
        version,
        key_type,
        threshold,
        share_count,
        share_index,
        secret_len,
        share,
        doc_hash,
        sign_pub,
        signature,
        shard_set_id,
    ) = _normalize_shard_payload_for_encoding(payload)

    data = {
        "version": version,
        "type": key_type,
        "threshold": threshold,
        "share_count": share_count,
        "share_index": share_index,
        "length": secret_len,
        "share": share,
        "hash": doc_hash,
        "pub": sign_pub,
        "sig": signature,
    }
    if version == SHARD_VERSION:
        data["set_id"] = shard_set_id
    return dumps_canonical(data)


def decode_shard_payload(data: bytes) -> ShardPayload:
    """Decode and validate a shard payload from canonical CBOR."""

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
    version = require_int(decoded["version"], label="shard version")
    key_type = decoded["type"]
    threshold = decoded["threshold"]
    share_count = decoded["share_count"]
    share_index = decoded["share_index"]
    secret_len = decoded["length"]
    share = decoded["share"]
    doc_hash = decoded["hash"]
    sign_pub = decoded["pub"]
    signature = decoded["sig"]
    if version not in (LEGACY_SHARD_VERSION, SHARD_VERSION):
        raise ValueError(f"unsupported shard payload version: {version}")
    if key_type not in (KEY_TYPE_PASSPHRASE, KEY_TYPE_SIGNING_SEED):
        raise ValueError(f"unsupported shard key type: {key_type}")
    threshold = require_positive_int(threshold, label="shard threshold")
    if threshold > MAX_SHARES:
        raise ValueError(f"shard threshold must be <= {MAX_SHARES}")
    share_count = require_positive_int(share_count, label="shard share_count")
    if share_count > MAX_SHARES:
        raise ValueError(f"shard share_count must be <= {MAX_SHARES}")
    share_index = require_positive_int(share_index, label="shard share_index")
    if share_index > MAX_SHARES:
        raise ValueError(f"shard share_index must be <= {MAX_SHARES}")
    if threshold > share_count:
        raise ValueError("shard threshold cannot exceed share_count")
    if share_index > share_count:
        raise ValueError("shard share_index cannot exceed share_count")
    secret_len = require_positive_int(secret_len, label="shard length")
    if key_type == KEY_TYPE_SIGNING_SEED and secret_len != ED25519_SEED_LEN:
        raise ValueError(f"signing-seed shard length must be {ED25519_SEED_LEN} bytes")
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
    shard_set_id: bytes | None = None
    if version == SHARD_VERSION:
        shard_set_id = require_bytes(
            decoded.get("set_id"),
            SHARD_SET_ID_LEN,
            label="set_id",
            prefix="shard ",
        )
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
        version=version,
        shard_set_id=shard_set_id,
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
    """Split a secret into fixed-size Shamir blocks and sign each share."""

    if key_type == KEY_TYPE_SIGNING_SEED and len(secret) != ED25519_SEED_LEN:
        raise ValueError(f"signing seed must be {ED25519_SEED_LEN} bytes")

    if threshold <= 0 or shares <= 0:
        raise ValueError("threshold and shares must be positive")
    if threshold > shares:
        raise ValueError("threshold cannot exceed shares")
    if threshold > MAX_SHARES or shares > MAX_SHARES:
        raise ValueError(f"threshold and shares must be <= {MAX_SHARES}")
    shard_set_id = secrets.token_bytes(SHARD_SET_ID_LEN)

    blocks: list[bytes] = []
    for offset in range(0, len(secret), BLOCK_SIZE):
        block = secret[offset : offset + BLOCK_SIZE]
        if len(block) < BLOCK_SIZE:
            block = block.ljust(BLOCK_SIZE, b"\x00")
        blocks.append(block)

    share_map: dict[int, bytearray] = {}
    for block in blocks:
        for index, share in Shamir.split(threshold, shares, block, False):
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
            shard_set_id=shard_set_id,
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
                version=SHARD_VERSION,
                shard_set_id=shard_set_id,
            )
        )
    return payloads


def _normalize_shard_payload_for_encoding(
    payload: ShardPayload,
) -> tuple[int, str, int, int, int, int, bytes, bytes, bytes, bytes, bytes | None]:
    """Validate shard payload fields before canonical encoding."""

    version = require_int(payload.version, label="shard version")
    if version not in (LEGACY_SHARD_VERSION, SHARD_VERSION):
        raise ValueError(f"unsupported shard payload version: {version}")
    key_type = payload.key_type
    if key_type not in (KEY_TYPE_PASSPHRASE, KEY_TYPE_SIGNING_SEED):
        raise ValueError(f"unsupported shard key type: {key_type}")
    threshold = require_positive_int(payload.threshold, label="shard threshold")
    if threshold > MAX_SHARES:
        raise ValueError(f"shard threshold must be <= {MAX_SHARES}")
    share_count = require_positive_int(payload.share_count, label="shard share_count")
    if share_count > MAX_SHARES:
        raise ValueError(f"shard share_count must be <= {MAX_SHARES}")
    share_index = require_positive_int(payload.share_index, label="shard share_index")
    if share_index > MAX_SHARES:
        raise ValueError(f"shard share_index must be <= {MAX_SHARES}")
    if threshold > share_count:
        raise ValueError("shard threshold cannot exceed share_count")
    if share_index > share_count:
        raise ValueError("shard share_index cannot exceed share_count")
    secret_len = require_positive_int(payload.secret_len, label="shard length")
    if key_type == KEY_TYPE_SIGNING_SEED and secret_len != ED25519_SEED_LEN:
        raise ValueError(f"signing-seed shard length must be {ED25519_SEED_LEN} bytes")
    if not isinstance(payload.share, (bytes, bytearray)) or not payload.share:
        raise ValueError("shard share must be bytes")
    share = bytes(payload.share)
    if len(share) % BLOCK_SIZE != 0:
        raise ValueError("shard share length must be a multiple of block size")
    if secret_len > len(share):
        raise ValueError("shard length cannot exceed share length")
    expected_len = ((secret_len + BLOCK_SIZE - 1) // BLOCK_SIZE) * BLOCK_SIZE
    if len(share) != expected_len:
        raise ValueError("shard share length does not match secret length")
    doc_hash = require_bytes(payload.doc_hash, DOC_HASH_LEN, label="hash", prefix="shard ")
    sign_pub = require_bytes(payload.sign_pub, ED25519_PUB_LEN, label="pub", prefix="shard ")
    signature = require_bytes(payload.signature, ED25519_SIG_LEN, label="sig", prefix="shard ")
    shard_set_id: bytes | None = None
    if version == SHARD_VERSION:
        shard_set_id = require_bytes(
            payload.shard_set_id,
            SHARD_SET_ID_LEN,
            label="set_id",
            prefix="shard ",
        )
    elif payload.shard_set_id is not None:
        raise ValueError("shard set_id is not supported for shard version 1")
    return (
        version,
        key_type,
        threshold,
        share_count,
        share_index,
        secret_len,
        share,
        doc_hash,
        sign_pub,
        signature,
        shard_set_id,
    )


def validate_shard_set_consistency(
    shares: list[ShardPayload],
    *,
    verify_signatures: bool = True,
) -> None:
    """Reject share sets that are detectably mixed across different polynomials."""

    if not shares:
        raise ValueError("no shares provided")

    threshold = shares[0].threshold
    version = shares[0].version
    shard_set_id = shares[0].shard_set_id
    doc_hash = shares[0].doc_hash
    sign_pub = shares[0].sign_pub
    for share in shares:
        if share.version != version:
            raise ValueError("shard versions do not match")
        if not _same_shard_set_id(share.shard_set_id, shard_set_id):
            raise ValueError(_INCOMPATIBLE_SHARD_SET_MESSAGE)
        if not hmac.compare_digest(share.doc_hash, doc_hash):
            raise ValueError("shard document hashes do not match")
        if not hmac.compare_digest(share.sign_pub, sign_pub):
            raise ValueError("shard signing public keys do not match")
        if verify_signatures and not verify_shard(
            share.doc_hash,
            shard_version=share.version,
            key_type=share.key_type,
            threshold=share.threshold,
            share_count=share.share_count,
            share_index=share.share_index,
            secret_len=share.secret_len,
            share=share.share,
            shard_set_id=share.shard_set_id,
            sign_pub=share.sign_pub,
            signature=share.signature,
        ):
            raise ValueError("invalid shard signature")
    if version == LEGACY_SHARD_VERSION and threshold > 1 and len(shares) == threshold:
        raise ValueError(
            "legacy shard format requires more than the threshold number of shares "
            "to prove compatibility"
        )
    if len(shares) <= threshold:
        return

    secret_len = shares[0].secret_len
    block_count = (secret_len + BLOCK_SIZE - 1) // BLOCK_SIZE
    expected_len = block_count * BLOCK_SIZE
    ordered = sorted(shares, key=lambda item: item.share_index)

    for share in ordered:
        if len(share.share) != expected_len:
            raise ValueError("shard share length does not match secret length")

    source_shares = [(share.share_index, share.share) for share in ordered[:threshold]]
    for share in ordered[threshold:]:
        interpolated = interpolate_share_blocks(
            source_shares,
            target_index=share.share_index,
            block_count=block_count,
        )
        if not hmac.compare_digest(interpolated, share.share):
            raise ValueError(_INCOMPATIBLE_SHARD_SET_MESSAGE)


def _recover_secret(
    shares: list[ShardPayload],
    *,
    key_type: str,
    verify_signatures: bool,
) -> bytes:
    """Recover a secret from validated shard payloads of one key type."""

    if not shares:
        raise ValueError("no shares provided")
    threshold = shares[0].threshold
    secret_len = shares[0].secret_len
    share_total = shares[0].share_count
    if key_type == KEY_TYPE_SIGNING_SEED and secret_len != ED25519_SEED_LEN:
        raise ValueError(f"signing seed must be {ED25519_SEED_LEN} bytes")
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

    validate_shard_set_consistency(shares, verify_signatures=verify_signatures)
    source_shares = sorted(shares, key=lambda item: item.share_index)[:threshold]

    blocks: list[bytes] = []
    for block_idx in range(block_count):
        start = block_idx * BLOCK_SIZE
        end = start + BLOCK_SIZE
        pairs = [(share.share_index, share.share[start:end]) for share in source_shares]
        blocks.append(Shamir.combine(pairs, False))

    return b"".join(blocks)[:secret_len]


def _same_shard_set_id(left: bytes | None, right: bytes | None) -> bool:
    if left is None or right is None:
        return left is right
    return hmac.compare_digest(left, right)
