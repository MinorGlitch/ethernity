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
import re
import string
from dataclasses import dataclass
from typing import Sequence

_SIGNING_PUB_GROUP_SIZE = 4
_SIGNING_PUB_LINE_LENGTH = 40
PASSPHRASE_PRINT_MODE_LITERAL = "literal"
PASSPHRASE_PRINT_MODE_JSON = "json"
PASSPHRASE_PRINT_MODE_JSON_PARTS = "json-parts"
PASSPHRASE_LABEL = "Passphrase"
PASSPHRASE_JSON_LABEL = "Passphrase JSON"
PASSPHRASE_JSON_PARTS_LABEL = "Passphrase Parts"
PASSPHRASE_JSON_INSTRUCTIONS = "JSON-decode once; enter the decoded value without quotes."


@dataclass(frozen=True)
class RecoveryMeta:
    passphrase: str | None = None
    passphrase_lines: tuple[str, ...] = ()
    passphrase_label: str = PASSPHRASE_LABEL
    passphrase_print_mode: str = PASSPHRASE_PRINT_MODE_LITERAL
    passphrase_instructions: str = ""
    quorum_value: str | None = None
    quorum_label: str = "Shard Quorum"
    signing_pub_lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class RecoveryPassphraseDisplay:
    """Typed printable passphrase field with guidance separate from secret data."""

    label: str
    guidance: str
    value_lines: tuple[str, ...]
    print_mode: str


def wrap_passphrase(passphrase: str, *, words_per_line: int = 6) -> tuple[str, ...]:
    """Build a lossless printable representation of a passphrase.

    Plain printable ASCII separated by single spaces keeps the familiar grouped-word layout.
    Everything else is emitted as one ASCII-only JSON string literal so significant whitespace,
    controls, and Unicode can be reconstructed exactly instead of being silently normalized.
    """

    if not passphrase:
        return ()
    if not passphrase_uses_literal_print_mode(passphrase):
        return (json.dumps(passphrase, ensure_ascii=True),)
    words = passphrase.split(" ")
    return tuple(
        " ".join(words[idx : idx + words_per_line]) for idx in range(0, len(words), words_per_line)
    )


def passphrase_uses_literal_print_mode(passphrase: str) -> bool:
    """Return whether *passphrase* is unambiguous when printed literally."""

    return (
        bool(passphrase)
        and passphrase == passphrase.strip(" ")
        and "  " not in passphrase
        and all(character == " " or "!" <= character <= "~" for character in passphrase)
    )


def passphrase_print_mode(passphrase: str) -> str:
    """Return the lossless printable representation mode for *passphrase*."""

    if passphrase_uses_literal_print_mode(passphrase):
        return PASSPHRASE_PRINT_MODE_LITERAL
    return PASSPHRASE_PRINT_MODE_JSON


def passphrase_print_label(passphrase: str) -> str:
    """Return the operator-facing label describing how to read the printed value."""

    if passphrase_uses_literal_print_mode(passphrase):
        return PASSPHRASE_LABEL
    return PASSPHRASE_JSON_LABEL


def decode_printed_passphrase(lines: Sequence[str], *, print_mode: str) -> str:
    """Decode a complete printed passphrase representation for proof and tests."""

    if print_mode == PASSPHRASE_PRINT_MODE_LITERAL:
        return " ".join(lines)
    if print_mode == PASSPHRASE_PRINT_MODE_JSON:
        if len(lines) != 1:
            raise ValueError("JSON passphrase representation must contain exactly one line")
        decoded = json.loads(lines[0])
        if not isinstance(decoded, str):
            raise ValueError("JSON passphrase representation must decode to a string")
        return decoded
    if print_mode == PASSPHRASE_PRINT_MODE_JSON_PARTS:
        if not lines:
            raise ValueError("JSON passphrase parts representation cannot be empty")
        decoded_parts: list[str] = []
        expected_total = len(lines)
        for expected_number, line in enumerate(lines, start=1):
            part_label, separator, encoded_part = line.partition(" ")
            if not separator or not encoded_part:
                raise ValueError("JSON passphrase part is missing its numbered prefix")
            label_match = re.fullmatch(r"(\d+)/(\d+)", part_label)
            if label_match is None:
                raise ValueError("JSON passphrase part has an invalid numbered prefix")
            part_number, total_parts = (int(value) for value in label_match.groups())
            if part_number != expected_number or total_parts != expected_total:
                raise ValueError("JSON passphrase part numbering is incomplete or out of order")
            decoded_part = json.loads(encoded_part)
            if not isinstance(decoded_part, str):
                raise ValueError("JSON passphrase part must decode to a string")
            decoded_parts.append(decoded_part)
        return "".join(decoded_parts)
    raise ValueError(f"unsupported passphrase print mode: {print_mode!r}")


def recovery_passphrase_display(meta: RecoveryMeta) -> RecoveryPassphraseDisplay:
    """Return the typed printable passphrase field for a recovery document."""

    return RecoveryPassphraseDisplay(
        label=meta.passphrase_label,
        guidance=meta.passphrase_instructions,
        value_lines=meta.passphrase_lines,
        print_mode=meta.passphrase_print_mode,
    )


def split_signing_pub_tokens(lines: Sequence[str]) -> list[str]:
    tokens: list[str] = []
    hex_chars = set(string.hexdigits)
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        parts = line.split()
        if len(parts) == 1:
            compact = parts[0]
            if len(compact) > _SIGNING_PUB_GROUP_SIZE and all(ch in hex_chars for ch in compact):
                parts = [
                    compact[idx : idx + _SIGNING_PUB_GROUP_SIZE]
                    for idx in range(0, len(compact), _SIGNING_PUB_GROUP_SIZE)
                ]
        tokens.extend(part for part in parts if part)
    return tokens


def wrap_grouped_tokens(tokens: Sequence[str], *, line_length: int) -> tuple[str, ...]:
    if not tokens:
        return ()

    wrapped: list[str] = []
    current: list[str] = []
    current_len = 0
    for token in tokens:
        token_len = len(token)
        next_len = token_len if not current else current_len + 1 + token_len
        if current and next_len > line_length:
            wrapped.append(" ".join(current))
            current = [token]
            current_len = token_len
            continue
        current.append(token)
        current_len = next_len

    if current:
        wrapped.append(" ".join(current))
    return tuple(wrapped)


def normalize_signing_pub_lines(lines: Sequence[str]) -> tuple[str, ...]:
    tokens = split_signing_pub_tokens(lines)
    return wrap_grouped_tokens(tokens, line_length=_SIGNING_PUB_LINE_LENGTH)


def build_recovery_meta(
    *,
    passphrase: str | None,
    quorum_threshold: int | None,
    quorum_shares: int | None,
    signing_pub: bytes | None,
    quorum_label: str = "Shard Quorum",
) -> RecoveryMeta:
    if (quorum_threshold is None) != (quorum_shares is None):
        raise ValueError("quorum_threshold and quorum_shares must be provided together")
    if quorum_threshold is not None and quorum_threshold <= 0:
        raise ValueError("quorum_threshold must be positive")
    if quorum_shares is not None and quorum_shares <= 0:
        raise ValueError("quorum_shares must be positive")

    quorum_value = (
        None
        if quorum_threshold is None or quorum_shares is None
        else f"{quorum_threshold} of {quorum_shares}"
    )
    signing_pub_lines = normalize_signing_pub_lines((signing_pub.hex(),)) if signing_pub else ()
    return RecoveryMeta(
        passphrase=passphrase,
        passphrase_lines=wrap_passphrase(passphrase) if passphrase else (),
        passphrase_label=passphrase_print_label(passphrase) if passphrase else PASSPHRASE_LABEL,
        passphrase_print_mode=(
            passphrase_print_mode(passphrase) if passphrase else PASSPHRASE_PRINT_MODE_LITERAL
        ),
        passphrase_instructions=(
            PASSPHRASE_JSON_INSTRUCTIONS
            if passphrase and not passphrase_uses_literal_print_mode(passphrase)
            else ""
        ),
        quorum_value=quorum_value,
        quorum_label=quorum_label,
        signing_pub_lines=signing_pub_lines,
    )


def recovery_meta_lines_extra(meta: RecoveryMeta) -> int:
    signing_lines = 0
    if meta.signing_pub_lines:
        signing_lines = max(2, len(meta.signing_pub_lines) + 1)

    passphrase_lines = 0
    if meta.passphrase:
        passphrase_lines = max(1, len(meta.passphrase_lines)) + int(
            bool(meta.passphrase_instructions)
        )

    return int(meta.quorum_value is not None) + signing_lines + passphrase_lines


__all__ = [
    "PASSPHRASE_JSON_LABEL",
    "PASSPHRASE_JSON_INSTRUCTIONS",
    "PASSPHRASE_JSON_PARTS_LABEL",
    "PASSPHRASE_LABEL",
    "PASSPHRASE_PRINT_MODE_JSON",
    "PASSPHRASE_PRINT_MODE_JSON_PARTS",
    "PASSPHRASE_PRINT_MODE_LITERAL",
    "RecoveryMeta",
    "RecoveryPassphraseDisplay",
    "build_recovery_meta",
    "decode_printed_passphrase",
    "passphrase_print_label",
    "passphrase_print_mode",
    "passphrase_uses_literal_print_mode",
    "recovery_passphrase_display",
    "recovery_meta_lines_extra",
    "wrap_passphrase",
]
