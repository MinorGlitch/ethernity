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

"""Ed25519 signing helpers for auth and shard payloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa

from ..core.validation import (
    require_bytes,
    require_dict,
    require_int,
    require_keys,
    require_length,
    require_non_empty_bytes,
    require_non_empty_str,
    require_non_negative_int,
    require_positive_int,
)
from ..encoding.cbor import dumps_canonical, loads_canonical

AUTH_VERSION = 1
AUTH_DOMAIN = b"ETHERNITY-AUTH-V1"
SHARD_DOMAIN = b"ETHERNITY-SHARD-V1"

ED25519_PUB_DER_PREFIX = bytes.fromhex("302a300506032b6570032100")
ED25519_PUB_LEN = 32
ED25519_SEED_LEN = 32
ED25519_SIG_LEN = 64
DOC_HASH_LEN = 32


@dataclass(frozen=True)
class AuthPayload:
    """Decoded authentication payload fields."""

    version: int
    doc_hash: bytes
    sign_pub: bytes
    signature: bytes


def generate_signing_keypair() -> tuple[bytes, bytes]:
    """Generate an Ed25519 seed/public-key pair."""

    key = ECC.generate(curve="Ed25519")
    seed = cast(bytes | None, getattr(key, "seed", None))
    if seed is None:
        raise ValueError("missing Ed25519 seed")
    return seed, key.public_key().export_key(format="raw")


def derive_public_key(sign_priv: bytes) -> bytes:
    """Derive a raw Ed25519 public key from a seed."""

    key = _key_from_seed(sign_priv)
    return key.public_key().export_key(format="raw")


def _encode_auth_signed_payload(doc_hash: bytes, *, sign_pub: bytes) -> bytes:
    """Encode the canonical auth payload body that is signed and verified."""

    doc_hash = require_bytes(doc_hash, DOC_HASH_LEN, label="doc_hash")
    sign_pub = require_bytes(sign_pub, ED25519_PUB_LEN, label="sign_pub")
    payload = {
        "version": AUTH_VERSION,
        "hash": doc_hash,
        "pub": sign_pub,
    }
    return dumps_canonical(payload)


def sign_auth(doc_hash: bytes, *, sign_pub: bytes, sign_priv: bytes) -> bytes:
    """Sign an auth payload for a document hash."""

    signed = _encode_auth_signed_payload(doc_hash, sign_pub=sign_pub)
    return _sign_message(AUTH_DOMAIN + signed, sign_priv=sign_priv)


def verify_auth(doc_hash: bytes, *, sign_pub: bytes, signature: bytes) -> bool:
    """Verify an auth signature for a document hash."""

    try:
        signed = _encode_auth_signed_payload(doc_hash, sign_pub=sign_pub)
    except ValueError:
        return False
    return _verify_message(AUTH_DOMAIN + signed, sign_pub=sign_pub, signature=signature)


def sign_shard(
    doc_hash: bytes,
    *,
    shard_version: int,
    key_type: str,
    threshold: int,
    share_count: int,
    share_index: int,
    secret_len: int,
    share: bytes,
    sign_pub: bytes,
    sign_priv: bytes,
) -> bytes:
    """Sign a shard payload binding for a document hash and share metadata."""

    message = SHARD_DOMAIN + _encode_shard_signed_payload(
        doc_hash,
        shard_version=shard_version,
        key_type=key_type,
        threshold=threshold,
        share_count=share_count,
        share_index=share_index,
        secret_len=secret_len,
        share=share,
        sign_pub=sign_pub,
    )
    return _sign_message(message, sign_priv=sign_priv)


def verify_shard(
    doc_hash: bytes,
    *,
    shard_version: int,
    key_type: str,
    threshold: int,
    share_count: int,
    share_index: int,
    secret_len: int,
    share: bytes,
    sign_pub: bytes,
    signature: bytes,
) -> bool:
    """Verify a shard signature against shard metadata and document hash."""

    try:
        signed = _encode_shard_signed_payload(
            doc_hash,
            shard_version=shard_version,
            key_type=key_type,
            threshold=threshold,
            share_count=share_count,
            share_index=share_index,
            secret_len=secret_len,
            share=share,
            sign_pub=sign_pub,
        )
    except ValueError:
        return False
    return _verify_message(
        SHARD_DOMAIN + signed,
        sign_pub=sign_pub,
        signature=signature,
    )


def encode_auth_payload(doc_hash: bytes, *, sign_pub: bytes, signature: bytes) -> bytes:
    """Encode an auth payload as canonical CBOR."""

    doc_hash = require_bytes(doc_hash, DOC_HASH_LEN, label="doc_hash")
    sign_pub = require_bytes(sign_pub, ED25519_PUB_LEN, label="sign_pub")
    signature = require_bytes(signature, ED25519_SIG_LEN, label="signature")
    payload = {
        "version": AUTH_VERSION,
        "hash": doc_hash,
        "pub": sign_pub,
        "sig": signature,
    }
    return dumps_canonical(payload)


def decode_auth_payload(data: bytes) -> AuthPayload:
    """Decode and validate an auth payload from canonical CBOR."""

    decoded = require_dict(loads_canonical(data, label="auth payload"), label="auth payload")
    require_keys(decoded, ("version", "hash", "pub", "sig"), label="auth payload")
    version = decoded["version"]
    doc_hash = decoded["hash"]
    sign_pub = decoded["pub"]
    signature = decoded["sig"]
    version = require_int(version, label="auth version")
    if version != AUTH_VERSION:
        raise ValueError(f"unsupported auth version: {version}")
    doc_hash = require_bytes(doc_hash, DOC_HASH_LEN, label="hash", prefix="auth ")
    sign_pub = require_bytes(sign_pub, ED25519_PUB_LEN, label="pub", prefix="auth ")
    signature = require_bytes(signature, ED25519_SIG_LEN, label="sig", prefix="auth ")
    return AuthPayload(
        version=version,
        doc_hash=doc_hash,
        sign_pub=sign_pub,
        signature=signature,
    )


def _key_from_seed(seed: bytes) -> ECC.EccKey:
    """Construct an Ed25519 private key from raw seed bytes."""

    require_length(seed, ED25519_SEED_LEN, label="sign_priv")
    return ECC.construct(curve="Ed25519", seed=cast(Any, seed))


def _key_from_public_bytes(sign_pub: bytes) -> ECC.EccKey:
    """Construct an Ed25519 public key from raw public key bytes."""

    require_length(sign_pub, ED25519_PUB_LEN, label="sign_pub")
    return ECC.import_key(ED25519_PUB_DER_PREFIX + sign_pub)


def _encode_shard_signed_payload(
    doc_hash: bytes,
    *,
    shard_version: int,
    key_type: str,
    threshold: int,
    share_count: int,
    share_index: int,
    secret_len: int,
    share: bytes,
    sign_pub: bytes,
) -> bytes:
    """Encode the canonical shard payload body that is signed and verified."""

    doc_hash = require_bytes(doc_hash, DOC_HASH_LEN, label="doc_hash")
    sign_pub = require_bytes(sign_pub, ED25519_PUB_LEN, label="sign_pub")
    shard_version = require_non_negative_int(shard_version, label="shard_version")
    key_type = require_non_empty_str(key_type, label="key_type")
    threshold = require_positive_int(threshold, label="threshold")
    share_count = require_positive_int(share_count, label="share_count")
    share_index = require_positive_int(share_index, label="share_index")
    if threshold > share_count:
        raise ValueError("threshold cannot exceed share_count")
    if share_index > share_count:
        raise ValueError("share_index cannot exceed share_count")
    secret_len = require_positive_int(secret_len, label="secret_len")
    share = require_non_empty_bytes(share, label="share")
    payload = {
        "version": shard_version,
        "type": key_type,
        "threshold": threshold,
        "share_count": share_count,
        "share_index": share_index,
        "length": secret_len,
        "share": share,
        "hash": doc_hash,
        "pub": sign_pub,
    }
    return dumps_canonical(payload)


def _sign_message(message: bytes, *, sign_priv: bytes) -> bytes:
    """Sign a message with Ed25519 private key."""
    key = _key_from_seed(sign_priv)
    signer = eddsa.new(key, mode="rfc8032")
    return signer.sign(message)


def _verify_message(message: bytes, *, sign_pub: bytes, signature: bytes) -> bool:
    """Verify an Ed25519 signature. Returns False on any error."""
    try:
        key = _key_from_public_bytes(sign_pub)
        verifier = eddsa.new(key, mode="rfc8032")
        verifier.verify(message, signature)
    except (ValueError, TypeError):
        return False
    return True
