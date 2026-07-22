from __future__ import annotations

import base64

import pytest

from ethernity.crypto.age_policy import (
    MAX_AUTOMATIC_KDF_WORK,
    MAX_AUTOMATIC_SCRYPT_LOG_N,
    RESOURCE_INTENSIVE_COMPATIBILITY_REQUIRED,
    KdfBudget,
    inspect_age_scrypt_stanza,
    preflight_age_scrypt,
    recovery_kdf_budget,
)


def _synthetic_age_document(log_n: int) -> bytes:
    salt = base64.b64encode(b"s" * 16).rstrip(b"=")
    body = base64.b64encode(b"b" * 32).rstrip(b"=")
    mac = base64.b64encode(b"m" * 32).rstrip(b"=")
    return b"\n".join(
        (
            b"age-encryption.org/v1",
            b"-> scrypt " + salt + b" " + str(log_n).encode("ascii"),
            body,
            b"--- " + mac,
            b"payload",
        )
    )


def test_public_stanza_preflight_reports_scrypt_cost() -> None:
    profile = inspect_age_scrypt_stanza(_synthetic_age_document(18))

    assert profile.log_n == 18
    assert profile.work == 2**18
    assert profile.memory_bytes == 128 * 8 * (2**18 + 2)


def test_excessive_scrypt_parameters_are_hard_rejected() -> None:
    with pytest.raises(ValueError, match="hard limit 21"):
        inspect_age_scrypt_stanza(_synthetic_age_document(22))


def test_compatibility_profile_requires_explicit_resource_intensive_scope() -> None:
    document = _synthetic_age_document(MAX_AUTOMATIC_SCRYPT_LOG_N + 1)

    with pytest.raises(ValueError, match=RESOURCE_INTENSIVE_COMPATIBILITY_REQUIRED):
        preflight_age_scrypt(document)

    with recovery_kdf_budget(allow_resource_intensive_compatibility=True) as budget:
        profile = preflight_age_scrypt(document)

    assert budget.consumed_work == profile.work


def test_cumulative_kdf_budget_is_charged_before_work_starts() -> None:
    document = _synthetic_age_document(18)
    budget = KdfBudget(maximum_work=(2**18) * 2)

    preflight_age_scrypt(document, budget=budget)
    preflight_age_scrypt(document, budget=budget)
    with pytest.raises(ValueError, match="cumulative scrypt work"):
        preflight_age_scrypt(document, budget=budget)

    assert budget.consumed_work <= MAX_AUTOMATIC_KDF_WORK


def test_nested_recovery_phases_share_one_cumulative_budget() -> None:
    document = _synthetic_age_document(18)

    with recovery_kdf_budget() as operation_budget:
        preflight_age_scrypt(document)
        with recovery_kdf_budget() as phase_budget:
            preflight_age_scrypt(document)

    assert phase_budget is operation_budget
    assert operation_budget.consumed_work == 2 * (2**18)


def test_nested_phase_cannot_enable_intensive_mode() -> None:
    with recovery_kdf_budget():
        with pytest.raises(ValueError, match="operation boundary"):
            with recovery_kdf_budget(allow_resource_intensive_compatibility=True):
                pass
