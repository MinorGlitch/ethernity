"""Fail-closed public-stanza policy for age passphrase recipients."""

from __future__ import annotations

import base64
import binascii
import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from ethernity.core.failures import FailureStage

MAX_AGE_HEADER_BYTES = 64 * 1024
MAX_AGE_HEADER_LINE_BYTES = 4096
MAX_RECOVERY_SCRYPT_LOG_N = 21
MAX_RECOVERY_KDF_WORK = 8 * (2**MAX_RECOVERY_SCRYPT_LOG_N)


class RecoveryResourceLimitError(ValueError):
    """Recovery cannot proceed within the fixed resource limits."""

    code = "RECOVERY_RESOURCE_LIMIT"
    stage = FailureStage.UNLOCK


@dataclass(frozen=True, slots=True)
class AgeScryptProfile:
    log_n: int
    work: int
    memory_bytes: int


@dataclass(slots=True)
class KdfBudget:
    """Cumulative scrypt work budget for one user operation."""

    maximum_work: int
    consumed_work: int = 0

    def charge(self, profile: AgeScryptProfile) -> None:
        next_total = self.consumed_work + profile.work
        if next_total > self.maximum_work:
            raise RecoveryResourceLimitError(
                f"cumulative scrypt work exceeds the recovery KDF budget ({self.maximum_work})"
            )
        self.consumed_work = next_total


_active_kdf_budget: contextvars.ContextVar[KdfBudget | None] = contextvars.ContextVar(
    "ethernity_active_kdf_budget",
    default=None,
)


@contextmanager
def recovery_kdf_budget() -> Iterator[KdfBudget]:
    """Share one cumulative KDF budget across a recovery operation."""

    active_budget = _active_kdf_budget.get()
    if active_budget is not None:
        yield active_budget
        return

    budget = KdfBudget(maximum_work=MAX_RECOVERY_KDF_WORK)
    budget_token = _active_kdf_budget.set(budget)
    try:
        yield budget
    finally:
        _active_kdf_budget.reset(budget_token)


def preflight_age_scrypt(
    data: bytes,
    *,
    budget: KdfBudget | None = None,
) -> AgeScryptProfile:
    """Inspect and charge an age scrypt stanza before starting its KDF."""

    profile = inspect_age_scrypt_stanza(data)
    selected_budget = budget or _active_kdf_budget.get()
    if selected_budget is None:
        selected_budget = KdfBudget(maximum_work=MAX_RECOVERY_KDF_WORK)
    selected_budget.charge(profile)
    return profile


def inspect_age_scrypt_stanza(data: bytes) -> AgeScryptProfile:
    """Parse the bounded public age header and return its scrypt cost."""

    if len(data) < 1:
        raise ValueError("invalid empty age ciphertext")
    header_end = data.find(b"\n--- ")
    if header_end < 0 or header_end + 6 > MAX_AGE_HEADER_BYTES:
        raise ValueError("invalid or excessive age header")
    header = data[:header_end]
    lines = header.split(b"\n")
    if len(lines) < 3 or lines[0] != b"age-encryption.org/v1":
        raise ValueError("unsupported age header")
    if any(len(line) > MAX_AGE_HEADER_LINE_BYTES for line in lines):
        raise ValueError("age header line exceeds the hard limit")

    stanza = lines[1].split(b" ")
    if len(stanza) != 4 or stanza[:2] != [b"->", b"scrypt"]:
        raise ValueError("age ciphertext must contain one passphrase scrypt recipient")
    if any(line.startswith(b"-> ") for line in lines[2:]):
        raise ValueError("age ciphertext contains multiple recipient stanzas")

    salt = _decode_base64_no_padding(stanza[2])
    if len(salt) != 16:
        raise ValueError("invalid age scrypt salt")
    log_n = _parse_scrypt_work_factor(stanza[3])
    work = 2**log_n
    return AgeScryptProfile(log_n=log_n, work=work, memory_bytes=128 * 8 * (work + 2))


def _parse_scrypt_work_factor(raw: bytes) -> int:
    try:
        log_n_text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("invalid age scrypt work factor") from exc
    if not log_n_text.isdecimal() or log_n_text.startswith("0"):
        raise ValueError("invalid age scrypt work factor")
    log_n = int(log_n_text, 10)
    if log_n < 1 or log_n > MAX_RECOVERY_SCRYPT_LOG_N:
        raise RecoveryResourceLimitError(
            f"age scrypt logN={log_n} exceeds the hard limit {MAX_RECOVERY_SCRYPT_LOG_N}"
        )
    return log_n


def _decode_base64_no_padding(value: bytes) -> bytes:
    try:
        return base64.b64decode(value + b"=" * (-len(value) % 4), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid age scrypt salt") from exc
