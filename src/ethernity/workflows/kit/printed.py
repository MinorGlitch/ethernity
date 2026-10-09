"""Self-identifying printed kit fragments and the offline assembly page."""

from __future__ import annotations

import hashlib
import json
import zlib
from importlib.resources import files

from ethernity.qr.capacity import fits_qr_payload
from ethernity.qr.codec import QrConfig

BASE44_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ$%*+-./:"
_BASE44_BLOCK_BYTES = 15
# ceil(log_44(256**n)) for each possible block length, without floating-point rounding.
_BASE44_DIGIT_COUNTS = (0, 2, 3, 5, 6, 8, 9, 11, 12, 14, 15, 17, 18, 20, 21, 22)
_ENCODING_ID = b"base44-15"
STARTUP_CODES = 2
HEADER_SIZE = len("EK1:000000000000:0000:0000:0000:00000000:")
_ASSEMBLER_RESOURCE = "recovery_kit.assembler.html"
_STARTUP_BOUNDARY = "<textarea hidden id=code>"


def encode_base44(data: bytes) -> str:
    """Encode 15-byte big-endian blocks as 22 digits, least significant digit first."""
    output: list[str] = []
    for offset in range(0, len(data), _BASE44_BLOCK_BYTES):
        part = data[offset : offset + _BASE44_BLOCK_BYTES]
        value = int.from_bytes(part, "big")
        for _ in range(_BASE44_DIGIT_COUNTS[len(part)]):
            value, digit = divmod(value, 44)
            output.append(BASE44_ALPHABET[digit])
    return "".join(output)


def _startup_payloads(config: list[str | int]) -> list[bytes]:
    template = files("ethernity.resources").joinpath("kit", _ASSEMBLER_RESOURCE).read_text()
    html = template.replace("__KIT_CONFIG__", json.dumps(config, separators=(",", ":")))
    shell, separator, code = html.partition(_STARTUP_BOUNDARY)
    if not separator or not code:
        raise ValueError("invalid generated kit assembler; rebuild the kit resources")
    return [(shell + separator).encode("ascii"), code.encode("ascii")]


def build_payloads(
    compressed: bytes, compression: str, chunk_size: int, config: QrConfig
) -> list[bytes]:
    """Count headers inside the size budget, keeping data codes in alphanumeric mode."""

    if chunk_size <= HEADER_SIZE:
        raise ValueError(f"chunk_size must exceed the {HEADER_SIZE}-character fragment header")
    if chunk_size > 0xFFFF:
        raise ValueError("chunk_size exceeds the printed kit length field")
    encoded = encode_base44(compressed)
    data_size = chunk_size - HEADER_SIZE
    chunks = [encoded[offset : offset + data_size] for offset in range(0, len(encoded), data_size)]
    total = len(chunks) + STARTUP_CODES
    if total > 0xFFFF:
        raise ValueError("too many printed kit fragments")
    # Bind the encoding and partition size as well as the software being printed.
    kit_id = (
        hashlib.sha256(_ENCODING_ID + compressed + chunk_size.to_bytes(4, "big"))
        .hexdigest()[:12]
        .upper()
    )
    payloads = _startup_payloads([kit_id, total, len(encoded), compression])
    for payload in payloads:
        if not fits_qr_payload(payload, config):
            raise ValueError("QR settings cannot encode the kit startup codes; increase QR version")
    for index, data in enumerate(chunks, STARTUP_CODES + 1):
        prefix = f"EK1:{kit_id}:{index:04X}:{total:04X}:{len(data):04X}:"
        checksum = zlib.crc32((prefix + data).encode("ascii"))
        payload = f"{prefix}{checksum:08X}:{data}".encode("ascii")
        if not fits_qr_payload(payload, config):
            raise ValueError("chunk_size is too large for the current QR settings")
        payloads.append(payload)
    return payloads
