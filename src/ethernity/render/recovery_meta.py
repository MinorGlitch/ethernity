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


def build_recovery_meta(
    *,
    passphrase: str | None,
    quorum_threshold: int | None,
    quorum_shares: int | None,
    signing_pub: bytes | None,
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
        quorum_value=quorum_value,
        signing_pub_lines=signing_pub_lines,
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
    "build_recovery_meta",
    "recovery_meta_lines_extra",
]
