"""Shared standalone backup encoding and capacity validation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from ethernity.core.bounds import MAX_CIPHERTEXT_BYTES
from ethernity.crypto import encrypt_bytes_with_passphrase
from ethernity.formats import document_codec, payload_codec
from ethernity.formats.manifest import BackupFile

# This valid timestamp requires float64 in deterministic CBOR, reserving its widest encoding.
_CAPACITY_CREATED_AT = 0.1


def encode_standalone_backup(
    parts: Sequence[BackupFile],
    *,
    sealed: bool,
    signing_seed: bytes | None,
    input_origin: str,
    input_roots: Sequence[str],
    payload_codec_mode: payload_codec.PayloadEncodingMode = payload_codec.PAYLOAD_ENCODING_AUTO,
    created_at: float | None = None,
) -> tuple[bytes, bytes]:
    """Encode the standalone backup used for creation and Rebuild.

    Manifest, file-count, path, and decoded payload bounds are enforced by the
    shared format encoders. The raw payload is returned for publication reporting.
    """

    manifest, raw_payload = document_codec.build_manifest_and_payload(
        list(parts),
        sealed=sealed,
        signing_seed=signing_seed,
        input_origin=input_origin,
        input_roots=list(input_roots),
        created_at=created_at,
    )
    encoded_payload, codec, raw_len = payload_codec.encode_payload_for_manifest(
        raw_payload,
        mode=payload_codec_mode,
    )
    manifest = replace(manifest, payload_codec=codec, payload_raw_len=raw_len)
    return document_codec.encode_backup_document(encoded_payload, manifest), raw_payload


def require_standalone_capacity(
    parts: Sequence[BackupFile],
    *,
    signing_seed: bytes,
    passphrase: str,
    input_origin: str,
    input_roots: Sequence[str],
) -> int:
    """Validate a complete unsealed state using actual standalone encryption.

    Rebuild always uses automatic payload compression. Measuring the encrypted
    backup includes the manifest, document headers, age header, and stream overhead.
    A maximum-width valid creation timestamp reserves space for later Rebuilds;
    actual publication still records its current timestamp. No ciphertext is published.
    """

    backup_document, _raw_payload = encode_standalone_backup(
        parts,
        sealed=False,
        signing_seed=signing_seed,
        input_origin=input_origin,
        input_roots=input_roots,
        created_at=_CAPACITY_CREATED_AT,
    )
    ciphertext, _passphrase = encrypt_bytes_with_passphrase(backup_document, passphrase=passphrase)
    ciphertext_bytes = len(ciphertext)
    if ciphertext_bytes > MAX_CIPHERTEXT_BYTES:
        raise ValueError(
            f"standalone ciphertext exceeds MAX_CIPHERTEXT_BYTES ({MAX_CIPHERTEXT_BYTES}): "
            f"{ciphertext_bytes} bytes"
        )
    return ciphertext_bytes


__all__ = ["encode_standalone_backup", "require_standalone_capacity"]
