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

from mnemonic import Mnemonic

DEFAULT_PASSPHRASE_WORDS = 24
MNEMONIC_WORD_COUNTS = (12, 15, 18, 21, 24)


def generate_passphrase(*, words: int = DEFAULT_PASSPHRASE_WORDS) -> str:
    if words not in MNEMONIC_WORD_COUNTS:
        allowed = ", ".join(str(count) for count in MNEMONIC_WORD_COUNTS)
        raise ValueError(f"passphrase words must be one of {allowed}")
    strength = (words // 3) * 32
    mnemonic = Mnemonic("english")
    return mnemonic.generate(strength=strength)


def looks_like_bip39_mnemonic(passphrase: str) -> bool:
    words = passphrase.strip().split()
    if len(words) not in MNEMONIC_WORD_COUNTS:
        return False
    if not words:
        return False
    mnemonic = Mnemonic("english")
    wordset = set(mnemonic.wordlist)
    return all(word in wordset for word in words)


def validate_mnemonic_checksum_if_bip39(passphrase: str) -> None:
    if not looks_like_bip39_mnemonic(passphrase):
        return
    mnemonic = Mnemonic("english")
    if not mnemonic.check(passphrase):
        raise ValueError("invalid BIP-39 mnemonic checksum")
