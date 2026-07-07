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

"""Structured backup internals used by the Textual internals view."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

from ethernity.cli.features.backup.service import PreparedBackupRun
from ethernity.cli.shared.types import InputFile
from ethernity.crypto import signing as signing_module
from ethernity.encoding.zbase32 import encode_zbase32
from ethernity.formats import envelope_codec, payload_codec as payload_codec_module
from ethernity.formats.envelope_types import EnvelopeManifest, PayloadPart
from ethernity.render.recovery_lines import format_grouped_lines, format_hex_lines
from ethernity.tasks.models import TaskDiagnosticBlock, TaskDiagnostics

DEFAULT_DEBUG_MAX_BYTES = 1024


def build_backup_internals_diagnostics(
    prepared: PreparedBackupRun,
    *,
    passphrase: str | None,
    max_bytes: int | None = DEFAULT_DEBUG_MAX_BYTES,
) -> TaskDiagnostics:
    """Build a no-write backup internals snapshot for the diagnostics modal."""

    sign_priv, sign_pub = signing_module.generate_signing_keypair()
    envelope, payload, manifest = _prepare_debug_envelope(prepared, sign_priv)
    masked_passphrase = (
        _format_masked_text_secret(passphrase)
        if passphrase is not None
        else "auto-generated during encryption"
    )
    blocks = [
        TaskDiagnosticBlock(
            title="Secret Material",
            content=f"Passphrase\n{masked_passphrase}",
            sensitive_content=(f"Passphrase\n{passphrase}" if passphrase is not None else None),
        ),
        TaskDiagnosticBlock(title="Manifest JSON", content=_manifest_json(manifest)),
        TaskDiagnosticBlock(title="Input entries", content=_input_entries(prepared.input_files)),
        TaskDiagnosticBlock(
            title="Payload Preview (hex)",
            content=_hexdump(payload, max_bytes=max_bytes),
        ),
        TaskDiagnosticBlock(
            title="Envelope Preview (hex)",
            content=_hexdump(envelope, max_bytes=max_bytes),
        ),
        TaskDiagnosticBlock(
            title="Payload Preview (z-base-32)",
            content=_zbase32_preview(payload, max_bytes=max_bytes),
        ),
        TaskDiagnosticBlock(
            title="Signing Public Key (hex)",
            content="\n".join(format_hex_lines(sign_pub)),
        ),
        TaskDiagnosticBlock(
            title="Signing Private Key (hex)",
            content=_format_masked_bytes_secret(sign_priv),
            sensitive_content="\n".join(format_hex_lines(sign_priv)),
        ),
    ]
    return TaskDiagnostics(
        title="Backup internals",
        blocks=tuple(blocks),
    )


def _prepare_debug_envelope(
    prepared: PreparedBackupRun,
    sign_priv: bytes,
) -> tuple[bytes, bytes, EnvelopeManifest]:
    parts = [
        PayloadPart(path=item.relative_path, data=item.data, mtime=item.mtime)
        for item in prepared.input_files
    ]
    manifest, payload = envelope_codec.build_manifest_and_payload(
        parts,
        sealed=prepared.plan.sealed,
        signing_seed=sign_priv if not prepared.plan.sealed else None,
        input_origin=prepared.input_origin,
        input_roots=prepared.input_roots,
    )
    encoded_payload, payload_codec, payload_raw_len = (
        payload_codec_module.encode_payload_for_manifest(
            payload,
            mode=prepared.config.cli_defaults.backup.payload_codec,
        )
    )
    manifest = replace(
        manifest,
        payload_codec=payload_codec,
        payload_raw_len=payload_raw_len,
    )
    envelope = envelope_codec.encode_envelope(encoded_payload, manifest)
    return envelope, payload, manifest


def _manifest_json(manifest: EnvelopeManifest) -> str:
    return json.dumps(_json_safe(manifest.to_dict()), indent=2, sort_keys=True)


def _input_entries(input_files: tuple[InputFile, ...]) -> str:
    if not input_files:
        return "(no input files)"
    lines: list[str] = []
    for index, item in enumerate(input_files, start=1):
        source = str(item.source_path) if item.source_path is not None else "stdin"
        lines.append(f"{index}. {item.relative_path} ({len(item.data)} bytes) <- {source}")
    return "\n".join(lines)


def _hexdump(data: bytes, *, max_bytes: int | None) -> str:
    display, truncated = _truncate(data, max_bytes=max_bytes)
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
        lines.append(_truncation_message(truncated))
    return "\n".join(lines)


def _zbase32_preview(data: bytes, *, max_bytes: int | None) -> str:
    display, truncated = _truncate(data, max_bytes=max_bytes)
    lines = format_grouped_lines(encode_zbase32(display), group_size=4, line_length=80)
    if truncated:
        lines.append(_truncation_message(truncated))
    return "\n".join(lines) if lines else "(empty)"


def _truncate(data: bytes, *, max_bytes: int | None) -> tuple[bytes, int]:
    if max_bytes is not None and max_bytes > 0 and len(data) > max_bytes:
        return data[:max_bytes], len(data) - max_bytes
    return data, 0


def _truncation_message(truncated: int) -> str:
    return f"... truncated {truncated} bytes"


def _format_masked_text_secret(secret: str) -> str:
    raw = secret.encode("utf-8", "strict")
    digest = hashlib.blake2b(raw, digest_size=8).hexdigest()
    return f"<masked chars={len(secret)} bytes={len(raw)} blake2b8={digest}>"


def _format_masked_bytes_secret(secret: bytes) -> str:
    digest = hashlib.blake2b(secret, digest_size=8).hexdigest()
    return f"<masked bytes={len(secret)} blake2b8={digest}>"


def _json_safe(value: object) -> object:
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value
