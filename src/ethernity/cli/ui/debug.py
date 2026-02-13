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
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Sequence

import cbor2
from rich import box
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from ...core.models import DocumentPlan
from ...encoding.zbase32 import encode_zbase32
from ...formats.envelope_codec import encode_manifest
from ...formats.envelope_types import EnvelopeManifest
from ..api import build_kv_table, console, panel
from ..core.types import InputFile
from .state import isatty

if TYPE_CHECKING:
    from ...formats.envelope_types import ManifestFile


RenderMode = Literal["rich_tty", "plain"]


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


def _resolve_render_mode() -> RenderMode:
    if isatty(sys.__stdout__, sys.stdout):
        return "rich_tty"
    return "plain"


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


def _entry_path(entry: object) -> str:
    path = getattr(entry, "path", "payload.bin")
    return str(path)


def _entry_size(entry: object, data: bytes) -> int:
    size = getattr(entry, "size", None)
    if isinstance(size, int) and size >= 0:
        return size
    return len(data)


def _print_header(flow: str, subtitle: str, *, mode: RenderMode) -> None:
    if mode == "rich_tty":
        console.print(panel(f"{flow} Debug", Text(subtitle, style="subtitle"), style="accent"))
    else:
        console.print(f"=== {flow.lower()} debug ===", markup=False)
        console.print(subtitle, markup=False)
    console.print()


def _print_section_title(title: str, *, mode: RenderMode) -> None:
    if mode == "rich_tty":
        console.print(Rule(Text(title, style="title"), align="left", style="rule"))
    else:
        console.print(f"{title}:", markup=False)


def _print_kv_section(
    title: str,
    rows: Sequence[tuple[str, str]],
    *,
    mode: RenderMode,
) -> None:
    _print_section_title(title, mode=mode)
    if mode == "rich_tty":
        console.print(build_kv_table(rows))
    else:
        for key, value in rows:
            console.print(f"- {key}: {value}", markup=False)
    console.print()


def _print_text_section(title: str, text: str, *, mode: RenderMode) -> None:
    if mode == "rich_tty":
        console.print(panel(title, Text(text, style="muted"), style="panel"))
    else:
        console.print(f"{title}:", markup=False)
        console.print(text, markup=False)
    console.print()


def _print_manifest_section(manifest_bytes: bytes, *, mode: RenderMode) -> None:
    manifest_raw = _decode_manifest_raw(manifest_bytes)
    if manifest_raw is None:
        message = "(unable to decode manifest CBOR map)"
        if mode == "rich_tty":
            console.print(
                panel(
                    "Manifest CBOR map JSON",
                    Text(message, style="warning"),
                    style="warning",
                )
            )
        else:
            console.print("Manifest CBOR map JSON:", markup=False)
            console.print(message, markup=False)
        console.print()
        return

    manifest_json = json.dumps(manifest_raw, indent=2, sort_keys=True)
    if mode == "rich_tty":
        try:
            renderable: object = Syntax(manifest_json, "json", word_wrap=True)
        except (ValueError, TypeError):
            renderable = Text(manifest_json, style="muted")
        console.print(panel("Manifest CBOR map JSON", renderable, style="panel"))
    else:
        console.print("Manifest CBOR map JSON:", markup=False)
        console.print(manifest_json, markup=False)
    console.print()


def _print_recovered_entries_section(
    extracted: Sequence[tuple[ManifestFile | object, bytes]],
    *,
    mode: RenderMode,
) -> None:
    _print_section_title("Recovered Entries", mode=mode)
    if not extracted:
        console.print("(no entries)", markup=False)
        console.print()
        return

    limit = 20
    if mode == "rich_tty":
        table = Table(box=box.SIMPLE, show_header=True, header_style="accent")
        table.add_column("#", style="muted", no_wrap=True)
        table.add_column("Path")
        table.add_column("Bytes", justify="right", no_wrap=True)
        for index, (entry, data) in enumerate(extracted[:limit], start=1):
            table.add_row(str(index), _entry_path(entry), str(_entry_size(entry, data)))
        if len(extracted) > limit:
            remaining = len(extracted) - limit
            table.add_row("...", f"{remaining} more entries omitted", "")
        console.print(table)
    else:
        for entry, data in extracted[:limit]:
            console.print(
                f"- {_entry_path(entry)} ({_entry_size(entry, data)} bytes)",
                markup=False,
            )
        if len(extracted) > limit:
            remaining = len(extracted) - limit
            console.print(f"... omitted {remaining} additional entries", markup=False)
    console.print()


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
    mode = _resolve_render_mode()
    manifest_bytes = (
        encode_manifest(manifest) if isinstance(manifest, EnvelopeManifest) else manifest
    )

    _print_header("Backup", "Pre-encryption diagnostics", mode=mode)

    summary_rows: list[tuple[str, str]] = [
        ("Mode", "backup"),
        ("Input files", str(len(input_files))),
        ("Payload bytes", str(len(payload))),
        ("Envelope bytes", str(len(envelope))),
        ("Sealed", "yes" if plan.sealed else "no"),
    ]
    if base_dir is not None:
        summary_rows.append(("Base directory", str(base_dir)))
    if plan.sharding is not None:
        summary_rows.append(("Sharding", f"{plan.sharding.threshold} of {plan.sharding.shares}"))
    _print_kv_section("Summary", summary_rows, mode=mode)

    secret_rows: list[tuple[str, str]] = []
    if passphrase is not None:
        passphrase_display = (
            passphrase if options.reveal_secrets else _format_masked_text_secret(passphrase)
        )
        secret_rows.append(("Passphrase", passphrase_display))
    if signing_seed is not None:
        signing_seed_display = (
            "revealed in hex block below"
            if options.reveal_secrets
            else _format_masked_bytes_secret(signing_seed)
        )
        secret_rows.append(("Signing private key", signing_seed_display))
    if not secret_rows:
        secret_rows.append(("Secrets", "(none)"))
    _print_kv_section("Secrets", secret_rows, mode=mode)

    _print_manifest_section(manifest_bytes, mode=mode)

    _print_text_section(
        "Payload Preview (hex)",
        _hexdump(payload, max_bytes=options.max_bytes),
        mode=mode,
    )
    _print_text_section(
        "Envelope Preview (hex)",
        _hexdump(envelope, max_bytes=options.max_bytes),
        mode=mode,
    )
    payload_zbase = _format_zbase32_lines(payload, line_length=80, max_bytes=options.max_bytes)
    _print_text_section(
        "Payload Preview (z-base-32)",
        "\n".join(payload_zbase) if payload_zbase else "(empty)",
        mode=mode,
    )

    detail_rows: list[tuple[str, str]] = []
    if signing_seed_stored is not None:
        detail_rows.append(
            ("Signing seed stored in envelope", "yes" if signing_seed_stored else "no")
        )
    if signing_pub is not None:
        detail_rows.append(("Signing public key", "present (hex below)"))
    else:
        detail_rows.append(("Signing public key", "not available"))
    _print_kv_section("Backup Details", detail_rows, mode=mode)

    if signing_pub is not None:
        signing_pub_hex = "\n".join(_format_hex_lines(signing_pub, line_length=80))
        _print_text_section("Signing Public Key (hex)", signing_pub_hex, mode=mode)
    if signing_seed is not None and options.reveal_secrets:
        signing_seed_hex = "\n".join(_format_hex_lines(signing_seed, line_length=80))
        _print_text_section("Signing Private Key (hex, revealed)", signing_seed_hex, mode=mode)


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
    mode = _resolve_render_mode()
    manifest_bytes = encode_manifest(manifest)

    _print_header("Recover", "Post-decryption diagnostics", mode=mode)

    summary_rows = [
        ("Mode", "recover"),
        ("Ciphertext bytes", str(len(ciphertext))),
        ("Extracted files", str(len(extracted))),
        ("Auth status", auth_status),
        ("Rescue mode", "enabled" if allow_unsigned else "disabled"),
        ("Output target", output_path or "stdout"),
    ]
    _print_kv_section("Summary", summary_rows, mode=mode)

    if passphrase is None:
        secret_rows = [("Passphrase", "(none)")]
    else:
        passphrase_display = (
            passphrase if options.reveal_secrets else _format_masked_text_secret(passphrase)
        )
        secret_rows = [("Passphrase", passphrase_display)]
    _print_kv_section("Secrets", secret_rows, mode=mode)

    _print_manifest_section(manifest_bytes, mode=mode)

    if not extracted:
        recovered_preview = "(no entries)"
    else:
        preview_count = min(3, len(extracted))
        preview_lines: list[str] = []
        for index, (entry, data) in enumerate(extracted[:preview_count], start=1):
            preview_lines.append(f"entry {index}: {_entry_path(entry)}")
            preview_lines.append(_hexdump(data, max_bytes=options.max_bytes))
            if index < preview_count:
                preview_lines.append("")
        if len(extracted) > preview_count:
            remaining = len(extracted) - preview_count
            preview_lines.append(f"... omitted previews for {remaining} more entries")
        recovered_preview = "\n".join(preview_lines)
    _print_text_section("Recovered Payload Preview (hex)", recovered_preview, mode=mode)

    _print_text_section(
        "Ciphertext Preview (hex)",
        _hexdump(ciphertext, max_bytes=options.max_bytes),
        mode=mode,
    )

    _print_recovered_entries_section(extracted, mode=mode)
