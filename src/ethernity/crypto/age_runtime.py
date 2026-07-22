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

"""AGE encryption/decryption wrappers with normalized error handling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import pyrage
from pyrage import passphrase as pyrage_passphrase

from ethernity.core.bounds import MAX_CIPHERTEXT_BYTES, MAX_DECOMPRESSED_PAYLOAD_BYTES
from ethernity.crypto.age_policy import AgeScryptProfile, preflight_age_scrypt
from ethernity.crypto.passphrases import (
    DEFAULT_PASSPHRASE_WORDS,
    canonicalize_valid_bip39_mnemonic,
    generate_passphrase,
)
from ethernity.security.resource_worker import (
    DisposableWorkerError,
    WorkerLimits,
    run_disposable_worker,
)

_PYRAGE_DECRYPT_ERROR = cast(type[Exception], getattr(pyrage, "DecryptError", RuntimeError))
MAX_AGE_CIPHERTEXT_BYTES = MAX_CIPHERTEXT_BYTES
MAX_AGE_PLAINTEXT_BYTES = MAX_DECOMPRESSED_PAYLOAD_BYTES
AGE_WORKER_CPU_SECONDS = 90
AGE_WORKER_WALL_SECONDS = 120.0
AGE_WORKER_BASE_MEMORY_BYTES = 512 * 1024 * 1024
AGE_WORKER_MAX_MEMORY_BYTES = 3 * 1024 * 1024 * 1024


@dataclass
class AgeError(RuntimeError):
    """Backend-specific AGE runtime failure."""

    backend: str
    detail: str

    def __str__(self) -> str:
        message = self.detail.strip() or "unknown error"
        return f"age ({self.backend}) failed: {message}"


class PassphraseAuthenticationError(ValueError):
    """The supplied passphrase candidate did not authenticate the ciphertext."""

    def __init__(self, backend_error: AgeError) -> None:
        super().__init__("decryption failed")
        self.backend_error = backend_error


def _wrap_pyrage_error(exc: Exception) -> AgeError:
    """Normalize pyrage exceptions into `AgeError`."""

    detail = str(exc).strip() or exc.__class__.__name__
    return AgeError(backend="pyrage", detail=detail)


def _encrypt_with_pyrage(data: bytes, passphrase: str) -> bytes:
    """Encrypt bytes with pyrage passphrase mode."""

    try:
        return pyrage_passphrase.encrypt(data, passphrase)
    except (ValueError, TypeError, RuntimeError, OSError) as exc:
        # pyrage can raise various exceptions for invalid input/state
        raise _wrap_pyrage_error(exc) from exc


def _decrypt_with_pyrage(data: bytes, passphrase: str) -> bytes:
    """Decrypt bytes with pyrage passphrase mode inside a bounded worker."""

    if len(data) > MAX_AGE_CIPHERTEXT_BYTES:
        raise ValueError(f"ciphertext exceeds the hard limit ({MAX_AGE_CIPHERTEXT_BYTES} bytes)")
    profile = preflight_age_scrypt(data)
    try:
        return _decrypt_with_pyrage_worker(data, passphrase, profile)
    except DisposableWorkerError as exc:
        raise AgeError(backend="pyrage-worker", detail=str(exc)) from exc
    except (ValueError, TypeError, RuntimeError, OSError, _PYRAGE_DECRYPT_ERROR) as exc:
        raise _wrap_pyrage_error(exc) from exc


def _decrypt_with_pyrage_worker(
    data: bytes,
    passphrase: str,
    profile: AgeScryptProfile,
) -> bytes:
    memory_limit = min(
        AGE_WORKER_MAX_MEMORY_BYTES,
        max(AGE_WORKER_BASE_MEMORY_BYTES, profile.memory_bytes + AGE_WORKER_BASE_MEMORY_BYTES),
    )
    return run_disposable_worker(
        "age decryption",
        _pyrage_decrypt_worker,
        (data, passphrase),
        limits=WorkerLimits(
            memory_bytes=memory_limit,
            cpu_seconds=AGE_WORKER_CPU_SECONDS,
            wall_seconds=AGE_WORKER_WALL_SECONDS,
            output_bytes=MAX_AGE_PLAINTEXT_BYTES,
        ),
    )


def _pyrage_decrypt_worker(data: bytes, passphrase: str) -> bytes:
    try:
        return pyrage_passphrase.decrypt(data, passphrase)
    except (ValueError, TypeError, RuntimeError, OSError, _PYRAGE_DECRYPT_ERROR) as exc:
        detail = str(exc).strip() or exc.__class__.__name__
        raise RuntimeError(detail) from exc


def _is_passphrase_authentication_error(exc: AgeError) -> bool:
    """Distinguish a wrong passphrase from malformed/truncated age input."""

    detail = exc.detail.strip().casefold()
    return detail == "decryption failed" or detail.endswith("worker failed: decryption failed")


def decrypt_bytes_with_exact_passphrase(
    data: bytes,
    *,
    passphrase: str,
) -> bytes:
    """Decrypt with exactly one candidate and preserve passphrase-auth failure identity."""

    try:
        return _decrypt_with_pyrage(data, passphrase)
    except AgeError as exc:
        if _is_passphrase_authentication_error(exc):
            raise PassphraseAuthenticationError(exc) from exc
        raise


def encrypt_bytes_with_passphrase(
    data: bytes,
    *,
    passphrase: str | None = None,
    passphrase_words: int | None = None,
) -> tuple[bytes, str | None]:
    """Encrypt bytes, generating a passphrase when one is not provided."""

    if passphrase is None:
        words = DEFAULT_PASSPHRASE_WORDS if passphrase_words is None else passphrase_words
        passphrase = generate_passphrase(words=words)
    else:
        passphrase = canonicalize_valid_bip39_mnemonic(passphrase)
    ciphertext = _encrypt_with_pyrage(data, passphrase)
    return ciphertext, passphrase


def decrypt_bytes(
    data: bytes,
    *,
    passphrase: str,
    debug: bool = False,
) -> bytes:
    """Decrypt bytes and hide backend details unless debug mode is enabled."""

    candidates = (passphrase,)
    canonical = canonicalize_valid_bip39_mnemonic(passphrase)
    if canonical != passphrase:
        candidates = (*candidates, canonical)
    last_error: AgeError | None = None
    for candidate in candidates:
        try:
            return decrypt_bytes_with_exact_passphrase(data, passphrase=candidate)
        except PassphraseAuthenticationError as exc:
            last_error = exc.backend_error
        except AgeError:
            if debug:
                raise
            raise ValueError("decryption failed") from None
    if debug and last_error is not None:
        raise last_error
    raise ValueError("decryption failed") from None
