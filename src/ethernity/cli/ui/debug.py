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

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

import cbor2

from ...core.models import DocumentPlan
from ...encoding.zbase32 import encode_zbase32
from ...formats.envelope_codec import encode_manifest
from ...formats.envelope_types import EnvelopeManifest
from ..api import console
from ..core.types import InputFile

if TYPE_CHECKING:
    from ...formats.envelope_types import ManifestFile


@dataclass(frozen=True)
class DebugRenderOptions:
    max_bytes: int | None
    reveal_secrets: bool


def _normalize_debug_max_bytes(value: int | None) -> int | None:
    if value is None or value <= 0:
        return None
    return value


def _resolve_render_options(*, max_bytes: int | None, reveal_secrets: bool) -> DebugRenderOptions:
    return DebugRenderOptions(
        max_bytes=_normalize_debug_max_bytes(max_bytes),
        reveal_secrets=reveal_secrets,
    )


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


def _format_masked_text_secret(secret: str) -> str:
    raw = secret.encode("utf-8", "strict")
    digest = hashlib.blake2b(raw, digest_size=8).hexdigest()
    return (
        f"<masked chars={len(secret)} bytes={len(raw)} blake2b8={digest}; "
        "use --debug-reveal-secrets to reveal>"
    )


def _format_masked_bytes_secret(secret: bytes) -> str:
    digest = hashlib.blake2b(secret, digest_size=8).hexdigest()
    return (
        f"<masked bytes={len(secret)} blake2b8={digest}; " "use --debug-reveal-secrets to reveal>"
    )


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


def _print_manifest_section(manifest_bytes: bytes) -> None:
    manifest_raw = _decode_manifest_raw(manifest_bytes)
    console.print("[bold]Manifest CBOR map JSON:[/bold]")
    if manifest_raw is None:
        console.print("(unable to decode manifest CBOR map)")
    else:
        console.print(
            json.dumps(manifest_raw, indent=2, sort_keys=True),
            markup=False,
        )
    console.print()


def _entry_path(entry: object) -> str:
    path = getattr(entry, "path", "payload.bin")
    return str(path)


def _entry_size(entry: object, data: bytes) -> int:
    size = getattr(entry, "size", None)
    if isinstance(size, int) and size >= 0:
        return size
    return len(data)


def print_backup_debug(
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
    reveal_secrets: bool = False,
) -> None:
    options = _resolve_render_options(max_bytes=debug_max_bytes, reveal_secrets=reveal_secrets)
    if isinstance(manifest, EnvelopeManifest):
        manifest_bytes = encode_manifest(manifest)
    else:
        manifest_bytes = manifest

    console.print("[bold]Debug Summary:[/bold]")
    console.print("- mode: backup", markup=False)
    console.print(f"- input file count: {len(input_files)}", markup=False)
    console.print(f"- payload bytes: {len(payload)}", markup=False)
    console.print(f"- envelope bytes: {len(envelope)}", markup=False)
    console.print(f"- sealed: {plan.sealed}", markup=False)
    if base_dir:
        console.print(f"- base dir: {base_dir}", markup=False)
    if passphrase is not None:
        passphrase_display = (
            passphrase if options.reveal_secrets else _format_masked_text_secret(passphrase)
        )
        console.print(f"- passphrase: {passphrase_display}", markup=False)
    if plan.sharding:
        console.print(
            f"- sharding: {plan.sharding.threshold} of {plan.sharding.shares}",
            markup=False,
        )
    if signing_seed_stored is not None:
        stored_label = "yes" if signing_seed_stored else "no"
        console.print(f"- signing seed stored in envelope: {stored_label}", markup=False)
    console.print()

    if signing_seed is not None or signing_pub is not None:
        console.print("[bold]Signing Material:[/bold]")
        if signing_pub is not None:
            console.print("Signing public key (hex):", markup=False)
            for line in _format_hex_lines(signing_pub, line_length=80):
                console.print(line, markup=False)
        if signing_seed is not None:
            if options.reveal_secrets:
                console.print("Signing private key (hex, revealed):", markup=False)
                for line in _format_hex_lines(signing_seed, line_length=80):
                    console.print(line, markup=False)
            else:
                console.print(
                    f"Signing private key: {_format_masked_bytes_secret(signing_seed)}",
                    markup=False,
                )
        console.print()

    _print_manifest_section(manifest_bytes)

    console.print("[bold]Payload Preview (hex):[/bold]")
    console.print(_hexdump(payload, max_bytes=options.max_bytes), markup=False)
    console.print()

    console.print("[bold]Envelope Preview (hex):[/bold]")
    console.print(_hexdump(envelope, max_bytes=options.max_bytes), markup=False)
    console.print()

    console.print("[bold]Payload Preview (z-base-32):[/bold]")
    for line in _format_zbase32_lines(payload, line_length=80, max_bytes=options.max_bytes):
        console.print(line, markup=False)
    console.print()


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
    """Compatibility wrapper for old call sites."""
    print_backup_debug(
        payload=payload,
        input_files=input_files,
        base_dir=base_dir,
        manifest=manifest,
        envelope=envelope,
        plan=plan,
        passphrase=passphrase,
        signing_seed=signing_seed,
        signing_pub=signing_pub,
        signing_seed_stored=signing_seed_stored,
        debug_max_bytes=debug_max_bytes,
        reveal_secrets=False,
    )


def print_recover_debug(
    *,
    manifest: EnvelopeManifest,
    extracted: Sequence[tuple[ManifestFile | object, bytes]],
    ciphertext: bytes,
    passphrase: str | None,
    auth_status: str,
    allow_unsigned: bool,
    output_path: str | None,
    debug_max_bytes: int | None,
    reveal_secrets: bool = False,
) -> None:
    options = _resolve_render_options(max_bytes=debug_max_bytes, reveal_secrets=reveal_secrets)
    manifest_bytes = encode_manifest(manifest)

    console.print("[bold]Debug Summary:[/bold]")
    console.print("- mode: recover", markup=False)
    console.print(f"- ciphertext bytes: {len(ciphertext)}", markup=False)
    console.print(f"- extracted files: {len(extracted)}", markup=False)
    console.print(f"- auth status: {auth_status}", markup=False)
    console.print(f"- rescue mode: {'enabled' if allow_unsigned else 'disabled'}", markup=False)
    console.print(f"- output target: {output_path or 'stdout'}", markup=False)
    if passphrase is not None:
        passphrase_display = (
            passphrase if options.reveal_secrets else _format_masked_text_secret(passphrase)
        )
        console.print(f"- passphrase: {passphrase_display}", markup=False)
    console.print()

    _print_manifest_section(manifest_bytes)

    console.print("[bold]Recovered Entries:[/bold]")
    if not extracted:
        console.print("(no entries)", markup=False)
    else:
        for entry, data in extracted:
            console.print(
                f"- {_entry_path(entry)} ({_entry_size(entry, data)} bytes)",
                markup=False,
            )
    console.print()

    console.print("[bold]Recovered Payload Preview (hex):[/bold]")
    if not extracted:
        console.print("(no entries)", markup=False)
    else:
        preview_count = min(3, len(extracted))
        for index, (entry, data) in enumerate(extracted[:preview_count], start=1):
            console.print(f"entry {index}: {_entry_path(entry)}", markup=False)
            console.print(_hexdump(data, max_bytes=options.max_bytes), markup=False)
            if index < preview_count:
                console.print()
        if len(extracted) > preview_count:
            remaining = len(extracted) - preview_count
            console.print(f"... omitted previews for {remaining} more entries", markup=False)
    console.print()

    console.print("[bold]Ciphertext Preview (hex):[/bold]")
    console.print(_hexdump(ciphertext, max_bytes=options.max_bytes), markup=False)
    console.print()
