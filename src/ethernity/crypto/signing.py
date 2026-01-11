#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import cbor2
from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa

from ..core.validation import require_bytes, require_length, require_list
from ..encoding.varint import encode_uvarint as _encode_uvarint

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
    version: int
    doc_hash: bytes
    sign_pub: bytes
    signature: bytes


def generate_signing_keypair() -> tuple[bytes, bytes]:
    key = ECC.generate(curve="Ed25519")
    seed = cast(bytes | None, getattr(key, "seed", None))
    if seed is None:
        raise ValueError("missing Ed25519 seed")
    return seed, key.public_key().export_key(format="raw")


def sign_auth(doc_hash: bytes, *, sign_priv: bytes) -> bytes:
    require_length(doc_hash, DOC_HASH_LEN, label="doc_hash")
    return _sign_message(AUTH_DOMAIN + doc_hash, sign_priv=sign_priv)


def verify_auth(doc_hash: bytes, *, sign_pub: bytes, signature: bytes) -> bool:
    require_length(doc_hash, DOC_HASH_LEN, label="doc_hash")
    return _verify_message(AUTH_DOMAIN + doc_hash, sign_pub=sign_pub, signature=signature)


def sign_shard(
    doc_hash: bytes,
    *,
    shard_index: int,
    share: bytes,
    sign_priv: bytes,
) -> bytes:
    require_length(doc_hash, DOC_HASH_LEN, label="doc_hash")
    if shard_index <= 0:
        raise ValueError("shard_index must be positive")
    if not share:
        raise ValueError("share cannot be empty")
    message = SHARD_DOMAIN + doc_hash + _encode_uvarint(shard_index) + share
    return _sign_message(message, sign_priv=sign_priv)


def verify_shard(
    doc_hash: bytes,
    *,
    shard_index: int,
    share: bytes,
    sign_pub: bytes,
    signature: bytes,
) -> bool:
    require_length(doc_hash, DOC_HASH_LEN, label="doc_hash")
    if shard_index <= 0:
        return False
    if not share:
        return False
    message = SHARD_DOMAIN + doc_hash + _encode_uvarint(shard_index) + share
    return _verify_message(message, sign_pub=sign_pub, signature=signature)


def encode_auth_payload(doc_hash: bytes, *, sign_pub: bytes, signature: bytes) -> bytes:
    require_length(doc_hash, DOC_HASH_LEN, label="doc_hash")
    require_length(sign_pub, ED25519_PUB_LEN, label="sign_pub")
    require_length(signature, ED25519_SIG_LEN, label="signature")
    payload = [AUTH_VERSION, doc_hash, sign_pub, signature]
    return cbor2.dumps(payload)


def decode_auth_payload(data: bytes) -> AuthPayload:
    decoded = require_list(cbor2.loads(data), 4, label="auth payload")
    version, doc_hash, sign_pub, signature = decoded[:4]
    if version != AUTH_VERSION:
        raise ValueError(f"unsupported auth version: {version}")
    doc_hash = require_bytes(doc_hash, DOC_HASH_LEN, label="doc_hash")
    sign_pub = require_bytes(sign_pub, ED25519_PUB_LEN, label="sign_pub")
    signature = require_bytes(signature, ED25519_SIG_LEN, label="signature")
    return AuthPayload(
        version=version,
        doc_hash=doc_hash,
        sign_pub=sign_pub,
        signature=signature,
    )


def _key_from_seed(seed: bytes) -> ECC.EccKey:
    require_length(seed, ED25519_SEED_LEN, label="sign_priv")
    return ECC.construct(curve="Ed25519", seed=cast(Any, seed))


def _key_from_public_bytes(sign_pub: bytes) -> ECC.EccKey:
    require_length(sign_pub, ED25519_PUB_LEN, label="sign_pub")
    return ECC.import_key(ED25519_PUB_DER_PREFIX + sign_pub)


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
