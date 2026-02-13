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

import json
from pathlib import Path

import cbor2

from ...core.models import DocumentPlan
from ...encoding.zbase32 import encode_zbase32
from ...formats.envelope_codec import encode_manifest
from ...formats.envelope_types import EnvelopeManifest
from ..api import console
from ..core.types import InputFile


def _normalize_debug_max_bytes(value: int | None) -> int | None:
    if value is None or value <= 0:
        return None
    return value


def _format_grouped_lines(
    encoded: str,
    *,
    group_size: int,
    line_length: int,
) -> list[str]:
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


def _format_zbase32_lines(
    data: bytes,
    *,
    group_size: int = 4,
    line_length: int = 80,
    max_bytes: int | None = None,
) -> list[str]:
    if max_bytes is not None and len(data) > max_bytes:
        display = data[:max_bytes]
        truncated = len(data) - max_bytes
    else:
        display = data
        truncated = 0
    encoded = encode_zbase32(display)
    lines = _format_grouped_lines(encoded, group_size=group_size, line_length=line_length)
    if truncated:
        lines.append(f"... truncated {truncated} bytes; use --debug-max-bytes 0 to disable")
    return lines


def _format_hex_lines(
    data: bytes,
    *,
    group_size: int = 4,
    line_length: int = 80,
) -> list[str]:
    encoded = data.hex()
    return _format_grouped_lines(encoded, group_size=group_size, line_length=line_length)


def _append_signing_key_lines(
    key_lines: list[str],
    *,
    sign_pub: bytes,
    sealed: bool,
    stored_in_main: bool,
    stored_as_shards: bool = False,
) -> None:
    key_lines.append("Signing public key (hex):")
    key_lines.extend(_format_hex_lines(sign_pub))
    if sealed:
        key_lines.append("Signing private key not stored (sealed backup).")
        return

    if stored_in_main:
        key_lines.append("Signing private key stored in main document.")
    if stored_as_shards:
        key_lines.append("Signing private key stored in separate shard documents.")
    if not stored_in_main and not stored_as_shards:
        key_lines.append("Signing private key not stored.")


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
    plan: DocumentPlan,
    passphrase: str | None,
    signing_seed: bytes | None = None,
    signing_pub: bytes | None = None,
    signing_seed_stored: bool | None = None,
    debug_max_bytes: int | None,
) -> None:
    manifest_model_display: object | None = None
    if isinstance(manifest, EnvelopeManifest):
        manifest_bytes = encode_manifest(manifest)
        manifest_model_display = _json_safe(manifest.to_dict())
    else:
        manifest_bytes = manifest

    console.print("[bold]Payload summary:[/bold]")
    console.print(f"- input file count: {len(input_files)}")
    console.print(f"- payload bytes: {len(payload)}")
    if base_dir:
        console.print(f"- base dir: {base_dir}")
    console.print(f"- envelope bytes: {len(envelope)}")
    console.print(f"- sealed: {plan.sealed}")
    if passphrase:
        console.print(f"- passphrase: {passphrase}")
    if plan.sharding:
        console.print(f"- sharding: {plan.sharding.threshold} of {plan.sharding.shares}")
    if signing_seed is not None or signing_pub is not None:
        console.print()
        console.print("[bold]Signing keys:[/bold]")
        if signing_pub is not None:
            console.print("Signing public key (hex):")
            for line in _format_hex_lines(signing_pub, line_length=80):
                console.print(line)
        if signing_seed is not None:
            if signing_seed_stored is True:
                label = "Signing seed (stored in envelope)"
            elif signing_seed_stored is False:
                label = "Signing seed (not stored in envelope)"
            else:
                label = "Signing seed"
            console.print(f"{label} (hex):")
            for line in _format_hex_lines(signing_seed, line_length=80):
                console.print(line)
        elif signing_seed_stored is not None:
            stored_label = "yes" if signing_seed_stored else "no"
            console.print(f"Signing seed stored in envelope: {stored_label}")
    console.print()

    console.print("[bold]Payload (hex):[/bold]")
    console.print(_hexdump(payload, max_bytes=debug_max_bytes), markup=False)
    console.print()

    manifest_raw = _decode_manifest_raw(manifest_bytes)
    if manifest_model_display is not None:
        console.print("[bold]Manifest model JSON:[/bold]")
        console.print(
            json.dumps(manifest_model_display, indent=2, sort_keys=True),
            markup=False,
        )
        console.print()

    console.print("[bold]Manifest CBOR map JSON:[/bold]")
    if manifest_raw is None:
        console.print("(unable to decode manifest CBOR map)")
    else:
        console.print(
            json.dumps(manifest_raw, indent=2, sort_keys=True),
            markup=False,
        )
    console.print()

    console.print("[bold]Envelope (hex):[/bold]")
    console.print(_hexdump(envelope, max_bytes=debug_max_bytes), markup=False)
    console.print()

    console.print("[bold]Payload z-base-32:[/bold]")
    for line in _format_zbase32_lines(payload, line_length=80, max_bytes=debug_max_bytes):
        console.print(line)
    console.print()


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
