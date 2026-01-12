#!/usr/bin/env python3
from __future__ import annotations

import base64
import binascii
from abc import ABC, abstractmethod
from typing import ClassVar


class PayloadEncoder(ABC):
    """Strategy interface for QR payload encoding/decoding."""

    name: ClassVar[str]
    aliases: ClassVar[tuple[str, ...]] = ()

    @abstractmethod
    def encode(self, data: bytes) -> bytes | str:
        """Encode bytes to payload format."""
        ...

    @abstractmethod
    def decode(self, payload: bytes | str) -> bytes:
        """Decode payload to bytes."""
        ...


class Base64Encoder(PayloadEncoder):
    """Base64 encoder with padding removal."""

    name = "base64"
    aliases = ("b64",)

    def encode(self, data: bytes) -> str:
        encoded = base64.b64encode(data).decode("ascii")
        return encoded.rstrip("=")

    def decode(self, payload: bytes | str) -> bytes:
        if isinstance(payload, bytes):
            try:
                text = payload.decode("ascii")
            except UnicodeDecodeError as exc:
                raise ValueError("invalid base64 QR payload") from exc
        else:
            text = payload
        cleaned = "".join(text.split())
        try:
            return base64.b64decode(_pad_base64(cleaned), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("invalid base64 QR payload") from exc


# Registry of available encoders
_ENCODERS: dict[str, PayloadEncoder] = {}


def _register_encoder(encoder: PayloadEncoder) -> None:
    _ENCODERS[encoder.name] = encoder
    for alias in encoder.aliases:
        _ENCODERS[alias] = encoder


# Register built-in encoders
_register_encoder(Base64Encoder())


def get_supported_encodings() -> set[str]:
    """Get set of canonical encoding names (excludes aliases)."""
    return {encoder.name for encoder in _ENCODERS.values()}


# Backward compatibility - this is now derived from registry
SUPPORTED_QR_PAYLOAD_ENCODINGS = get_supported_encodings()


def get_encoder(encoding: str | None) -> PayloadEncoder:
    """Get encoder by name, defaulting to base64."""
    if encoding is None:
        return _ENCODERS["base64"]
    normalized = encoding.strip().lower()
    encoder = _ENCODERS.get(normalized)
    if encoder is None:
        raise ValueError(f"unsupported QR payload encoding: {encoding}")
    return encoder


def normalize_qr_payload_encoding(value: str | None) -> str:
    """Normalize encoding name to canonical form."""
    return get_encoder(value).name


def encode_qr_payload(data: bytes, encoding: str) -> bytes | str:
    """Encode bytes using specified encoding strategy."""
    return get_encoder(encoding).encode(data)


def decode_qr_payload(payload: bytes | str, encoding: str) -> bytes:
    """Decode payload using specified encoding strategy."""
    return get_encoder(encoding).decode(payload)


def _pad_base64(text: str) -> str:
    """Add padding to base64 string."""
    padding = (-len(text)) % 4
    return text + ("=" * padding)
