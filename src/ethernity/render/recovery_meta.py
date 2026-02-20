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

import string
from dataclasses import dataclass
from typing import Sequence

_SIGNING_PUB_GROUP_SIZE = 4
_SIGNING_PUB_LINE_LENGTH = 40


@dataclass(frozen=True)
class RecoveryMeta:
    passphrase: str | None = None
    passphrase_lines: tuple[str, ...] = ()
    quorum_value: str | None = None
    signing_pub_lines: tuple[str, ...] = ()


def wrap_passphrase(passphrase: str, *, words_per_line: int = 6) -> tuple[str, ...]:
    words = passphrase.split()
    if not words:
        return ()
    return tuple(
        " ".join(words[idx : idx + words_per_line]) for idx in range(0, len(words), words_per_line)
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


def parse_recovery_key_lines(key_lines: Sequence[str]) -> RecoveryMeta:
    passphrase_label = "Passphrase:"
    quorum_prefix = "Recover with "
    quorum_suffix = " shard documents."
    signing_pub_label = "Signing public key (hex):"
    passphrase: str | None = None
    quorum_value: str | None = None
    pub_lines_raw: list[str] = []
    collecting_pub = False
    expecting_passphrase = False

    for line in key_lines:
        if expecting_passphrase:
            passphrase = line.strip() or None
            expecting_passphrase = False
            continue

        if line == passphrase_label:
            expecting_passphrase = True
            continue
        if line == signing_pub_label:
            collecting_pub = True
            continue
        if collecting_pub and line.startswith("Signing private key"):
            collecting_pub = False
            continue
        if line.startswith(quorum_prefix) and line.endswith(quorum_suffix):
            quorum_value = line.removeprefix(quorum_prefix).removesuffix(quorum_suffix).strip()
            continue
        if collecting_pub:
            pub_lines_raw.append(line)

    pub_lines = normalize_signing_pub_lines(pub_lines_raw)

    return RecoveryMeta(
        passphrase=passphrase,
        passphrase_lines=wrap_passphrase(passphrase) if passphrase else (),
        quorum_value=quorum_value,
        signing_pub_lines=pub_lines,
    )


def recovery_meta_lines_extra(meta: RecoveryMeta) -> int:
    signing_lines = 0
    if meta.signing_pub_lines:
        signing_lines = max(2, len(meta.signing_pub_lines) + 1)

    passphrase_lines = 0
    if meta.passphrase:
        passphrase_lines = max(1, len(meta.passphrase_lines))

    return int(meta.quorum_value is not None) + signing_lines + passphrase_lines


__all__ = [
    "RecoveryMeta",
    "parse_recovery_key_lines",
    "recovery_meta_lines_extra",
]
