#!/usr/bin/env python3
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
