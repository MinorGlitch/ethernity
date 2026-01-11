#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import pyrage
from pyrage import passphrase as pyrage_passphrase

from .passphrases import DEFAULT_PASSPHRASE_WORDS, generate_passphrase


@dataclass
class AgeCliError(RuntimeError):
    cmd: Sequence[str]
    returncode: int
    stderr: str

    def __str__(self) -> str:
        detail = self.stderr.strip() or "unknown error"
        return f"age failed (exit {self.returncode}): {detail}"


def _wrap_pyrage_error(exc: Exception) -> AgeCliError:
    detail = str(exc).strip() or exc.__class__.__name__
    return AgeCliError(cmd=("pyrage",), returncode=1, stderr=detail)


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
) -> bytes:
    return _decrypt_with_pyrage(data, passphrase)
