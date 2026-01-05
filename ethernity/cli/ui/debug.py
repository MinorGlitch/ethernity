#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cbor2

from ..core.types import InputFile
from ...encoding.fallback import encode_zbase32
from ...formats.envelope_codec import encode_manifest
from ...formats.envelope_types import EnvelopeManifest
from ...core.models import DocumentPlan


def _normalize_debug_max_bytes(value: int | None) -> int | None:
    if value is None or value <= 0:
        return None
    return value


def _format_zbase32_lines(
    data: bytes,
    *,
    group_size: int = 4,
    line_length: int = 80,
) -> list[str]:
    encoded = encode_zbase32(data)
    if not encoded:
        return []
    groups = [encoded[i : i + group_size] for i in range(0, len(encoded), group_size)]
    lines: list[str] = []
    current = ""
    for group in groups:
        candidate = group if not current else f"{current} {group}"
        if len(candidate) > line_length:
            lines.append(current)
            current = group
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _append_signing_key_lines(
    key_lines: list[str],
    *,
    sign_pub: bytes,
    sign_priv: bytes,
    sealed: bool,
) -> None:
    key_lines.append("Signing public key (z-base-32):")
    key_lines.extend(_format_zbase32_lines(sign_pub))
    if sealed:
        return
    key_lines.append("Signing private key (seed, z-base-32):")
    key_lines.extend(_format_zbase32_lines(sign_priv))


def _hexdump(data: bytes, *, max_bytes: int | None) -> str:
    if max_bytes is not None and len(data) > max_bytes:
        display = data[:max_bytes]
        truncated = len(data) - max_bytes
    else:
        display = data
        truncated = 0

    if not display:
        return "(empty)"

    width = 16
    lines = []
    for offset in range(0, len(display), width):
        chunk = display[offset : offset + width]
        hex_part = " ".join(f"{byte:02x}" for byte in chunk)
        ascii_part = "".join(chr(byte) if 32 <= byte < 127 else "." for byte in chunk)
        lines.append(f"{offset:08x}  {hex_part:<47}  |{ascii_part}|")
    if truncated:
        lines.append(f"... truncated {truncated} bytes; use --debug-max-bytes 0 to disable")
    return "\n".join(lines)


def _print_pre_encryption_debug(
    *,
    payload: bytes,
    input_files: list[InputFile],
    base_dir: Path | None,
    manifest: bytes | EnvelopeManifest,
    envelope: bytes,
    wrapped_envelope: bytes,
    compression: object,
    compression_info: object,
    plan: DocumentPlan,
    recipients: list[str],
    passphrase: str | None,
    identity: str | None,
    recipient_public: str | None,
    debug_max_bytes: int | None,
) -> None:
    if isinstance(manifest, EnvelopeManifest):
        manifest_bytes = encode_manifest(manifest)
        manifest_display: object | None = _json_safe(manifest.to_dict())
    else:
        manifest_bytes = manifest
        manifest_display = None

    print("Payload summary:")
    print(f"- input file count: {len(input_files)}")
    print(f"- payload bytes: {len(payload)}")
    if base_dir:
        print(f"- base dir: {base_dir}")
    print(f"- envelope bytes: {len(envelope)}")
    print(f"- wrapped envelope bytes: {len(wrapped_envelope)}")
    print(f"- compression: {compression}")
    print(f"- compression info: {compression_info}")
    print(f"- mode: {plan.mode.value}")
    print(f"- sealed: {plan.sealed}")
    if recipients:
        print(f"- recipients: {len(recipients)}")
    if passphrase:
        print(f"- passphrase: {passphrase}")
    if identity:
        print(f"- generated identity: {identity}")
    if recipient_public:
        print(f"- generated recipient: {recipient_public}")
    if plan.sharding:
        print(f"- sharding: {plan.sharding.threshold} of {plan.sharding.shares}")
    print()

    print("Payload (hex):")
    print(_hexdump(payload, max_bytes=debug_max_bytes))
    print()

    print("Manifest JSON:")
    manifest_raw = _decode_manifest_raw(manifest_bytes)
    if manifest_display is None:
        manifest_display = manifest_raw
    if manifest_display is None:
        print("(unable to decode manifest JSON)")
    else:
        print(json.dumps(manifest_display, indent=2, sort_keys=True))
    print()

    prefix_stats = _manifest_prefix_stats(manifest_raw)
    if prefix_stats:
        print("Manifest prefix summary:")
        print(json.dumps(prefix_stats, indent=2, sort_keys=True))
        print()

    print("Envelope (hex):")
    print(_hexdump(envelope, max_bytes=debug_max_bytes))
    print()

    print("Wrapped envelope (hex):")
    print(_hexdump(wrapped_envelope, max_bytes=debug_max_bytes))
    print()

    print("Payload z-base-32:")
    for line in _format_zbase32_lines(payload, line_length=80):
        print(line)
    print()


def _json_safe(value: object) -> object:
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _decode_manifest_raw(data: bytes) -> object | None:
    try:
        decoded = cbor2.loads(data)
    except (ValueError, cbor2.CBORDecodeError):
        decoded = None
    if decoded is not None:
        return _json_safe(decoded)
    try:
        decoded = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return _json_safe(decoded)


def _manifest_prefix_stats(raw: object) -> dict[str, object] | None:
    if isinstance(raw, dict):
        entries = raw.get("entries")
        prefixes = raw.get("prefixes")
    elif isinstance(raw, (list, tuple)) and len(raw) >= 5:
        prefixes = raw[3]
        entries = raw[4]
    else:
        return None
    if not isinstance(entries, list) or not isinstance(prefixes, list):
        return None

    file_count = 0
    total_suffix_len = 0
    total_full_len = 0
    used_prefixes = 0
    saved_chars = 0

    for entry in entries:
        if not isinstance(entry, list) or len(entry) < 2:
            continue
        prefix_idx = entry[0]
        suffix = entry[1]
        if not isinstance(prefix_idx, int) or not isinstance(suffix, str):
            continue
        if prefix_idx < 0 or prefix_idx >= len(prefixes):
            continue
        prefix = prefixes[prefix_idx]
        if not isinstance(prefix, str):
            continue
        file_count += 1
        total_suffix_len += len(suffix)
        total_full_len += len(suffix) + (len(prefix) + 1 if prefix else 0)
        if prefix:
            used_prefixes += 1
            saved_chars += len(prefix) + 1

    if file_count == 0:
        return None

    non_empty_prefixes = [p for p in prefixes if p]
    avg_prefix_len = (
        sum(len(p) for p in non_empty_prefixes) / len(non_empty_prefixes)
        if non_empty_prefixes
        else 0.0
    )

    return {
        "prefix_count": len(prefixes),
        "file_count": file_count,
        "avg_prefix_len": round(avg_prefix_len, 2),
        "avg_suffix_len": round(total_suffix_len / file_count, 2),
        "avg_full_path_len": round(total_full_len / file_count, 2),
        "files_with_prefix": used_prefixes,
        "estimated_saved_chars": saved_chars,
    }
