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
import importlib.resources
import secrets

DEFAULT_PASSPHRASE_WORDS = 24
MNEMONIC_WORD_COUNTS = (12, 15, 18, 21, 24)


def _load_wordlist() -> list[str]:
    ref = importlib.resources.files("ethernity.crypto") / "bip39_wordlist.txt"
    return ref.read_text(encoding="utf-8").splitlines()


_WORDLIST: list[str] = _load_wordlist()


def generate_passphrase(*, words: int = DEFAULT_PASSPHRASE_WORDS) -> str:
    if words not in MNEMONIC_WORD_COUNTS:
        allowed = ", ".join(str(count) for count in MNEMONIC_WORD_COUNTS)
        raise ValueError(f"passphrase words must be one of {allowed}")
    strength = (words // 3) * 32  # entropy bits: 128, 160, 192, 224, or 256
    entropy = secrets.token_bytes(strength // 8)
    checksum_bits = words // 3
    h = hashlib.sha256(entropy).digest()
    checksum = h[0] >> (8 - checksum_bits)
    entropy_int = int.from_bytes(entropy, "big")
    combined = (entropy_int << checksum_bits) | checksum
    indices = [(combined >> (11 * i)) & 0x7FF for i in range(words - 1, -1, -1)]
    return " ".join(_WORDLIST[i] for i in indices)


def looks_like_bip39_mnemonic(passphrase: str) -> bool:
    words = passphrase.strip().split()
    if len(words) not in MNEMONIC_WORD_COUNTS:
        return False
    wordset = set(_WORDLIST)
    return all(word in wordset for word in words)


def validate_mnemonic_checksum_if_bip39(passphrase: str) -> None:
    if not looks_like_bip39_mnemonic(passphrase):
        return
    words_list = passphrase.strip().split()
    n = len(words_list)
    word_to_idx = {w: i for i, w in enumerate(_WORDLIST)}
    indices = [word_to_idx[w] for w in words_list]
    combined = 0
    for idx in indices:
        combined = (combined << 11) | idx
    checksum_bits = n // 3
    checksum = combined & ((1 << checksum_bits) - 1)
    entropy_int = combined >> checksum_bits
    entropy = entropy_int.to_bytes(checksum_bits * 4, "big")
    h = hashlib.sha256(entropy).digest()
    expected_checksum = h[0] >> (8 - checksum_bits)
    if checksum != expected_checksum:
        raise ValueError("invalid BIP-39 mnemonic checksum")
