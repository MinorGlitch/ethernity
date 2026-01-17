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

from dataclasses import dataclass

import pyrage
from pyrage import passphrase as pyrage_passphrase

from .passphrases import DEFAULT_PASSPHRASE_WORDS, generate_passphrase


@dataclass
class AgeError(RuntimeError):
    backend: str
    detail: str

    def __str__(self) -> str:
        message = self.detail.strip() or "unknown error"
        return f"age ({self.backend}) failed: {message}"


def _wrap_pyrage_error(exc: Exception) -> AgeError:
    detail = str(exc).strip() or exc.__class__.__name__
    return AgeError(backend="pyrage", detail=detail)


def _encrypt_with_pyrage(data: bytes, passphrase: str) -> bytes:
    try:
        return pyrage_passphrase.encrypt(data, passphrase)
    except (ValueError, TypeError, RuntimeError, OSError) as exc:
        # pyrage can raise various exceptions for invalid input/state
        raise _wrap_pyrage_error(exc) from exc


def _decrypt_with_pyrage(data: bytes, passphrase: str) -> bytes:
    try:
        return pyrage_passphrase.decrypt(data, passphrase)
    except (ValueError, TypeError, RuntimeError, OSError, pyrage.DecryptError) as exc:
        # pyrage raises DecryptError for wrong passphrase, other exceptions for corrupted data
        raise _wrap_pyrage_error(exc) from exc


def encrypt_bytes_with_passphrase(
    data: bytes,
    *,
    passphrase: str | None = None,
    passphrase_words: int | None = None,
) -> tuple[bytes, str | None]:
    if passphrase is None:
        words = DEFAULT_PASSPHRASE_WORDS if passphrase_words is None else passphrase_words
        passphrase = generate_passphrase(words=words)
    ciphertext = _encrypt_with_pyrage(data, passphrase)
    return ciphertext, passphrase


def decrypt_bytes(
    data: bytes,
    *,
    passphrase: str,
    debug: bool = False,
) -> bytes:
    try:
        return _decrypt_with_pyrage(data, passphrase)
    except AgeError:
        if debug:
            raise
        raise ValueError("decryption failed") from None
