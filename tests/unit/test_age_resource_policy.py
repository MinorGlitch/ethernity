from __future__ import annotations

import base64
from pathlib import Path

import pytest

from ethernity.crypto.age_policy import (
    MAX_AUTOMATIC_KDF_WORK,
    MAX_AUTOMATIC_SCRYPT_LOG_N,
    MAX_COMPATIBILITY_KDF_WORK,
    RESOURCE_INTENSIVE_COMPATIBILITY_REQUIRED,
    KdfBudget,
    RecoveryWorkLimitExceeded,
    inspect_age_scrypt_stanza,
    preflight_age_scrypt,
    recovery_kdf_budget,
)
from ethernity.crypto.document_identity import doc_id_and_hash_from_ciphertext
from ethernity.encoding.framing import VERSION, Frame, FrameType
from ethernity.workflows.execution import RecoveryRequest, execute_recovery


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
        with pytest.raises(ValueError, match="when recovery starts"):
            with recovery_kdf_budget(allow_resource_intensive_compatibility=True):
                pass


def test_normal_work_limit_reports_memory_without_charging_the_rejected_work() -> None:
    document = _synthetic_age_document(21)
    with recovery_kdf_budget() as budget:
        with pytest.raises(RecoveryWorkLimitExceeded) as raised:
            preflight_age_scrypt(document)
    assert raised.value.memory_bytes == 128 * 8 * (2**21 + 2)
    assert budget.consumed_work == 0


def test_cumulative_limit_offers_one_higher_budget_then_fails_closed() -> None:
    document = _synthetic_age_document(20)
    with recovery_kdf_budget() as budget:
        for _ in range(4):
            preflight_age_scrypt(document)
        with pytest.raises(RecoveryWorkLimitExceeded) as raised:
            preflight_age_scrypt(document)
        assert raised.value.memory_bytes == 128 * 8 * (2**20 + 2)
        assert budget.consumed_work == MAX_AUTOMATIC_KDF_WORK

    with recovery_kdf_budget(allow_resource_intensive_compatibility=True) as budget:
        for _ in range(16):
            preflight_age_scrypt(document)
        with pytest.raises(ValueError) as raised:
            preflight_age_scrypt(document)
        assert not isinstance(raised.value, RecoveryWorkLimitExceeded)
        assert budget.consumed_work == MAX_COMPATIBILITY_KDF_WORK

    with pytest.raises(RecoveryWorkLimitExceeded):
        preflight_age_scrypt(_synthetic_age_document(21))


@pytest.mark.parametrize("higher_limits", (False, True))
def test_hard_work_limit_never_offers_a_retry(higher_limits: bool) -> None:
    with recovery_kdf_budget(allow_resource_intensive_compatibility=higher_limits):
        with pytest.raises(ValueError) as raised:
            preflight_age_scrypt(_synthetic_age_document(22))
    assert not isinstance(raised.value, RecoveryWorkLimitExceeded)


@pytest.mark.parametrize("document_count", (1, 2))
def test_restore_preserves_resource_failure_and_writes_nothing(
    tmp_path: Path, document_count: int
) -> None:
    frames = []
    for index in range(document_count):
        ciphertext = _synthetic_age_document(21) + bytes([index])
        doc_id, _doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
        frames.append(Frame(VERSION, FrameType.MAIN_DOCUMENT, doc_id, 0, 1, ciphertext))
    destination = tmp_path / "restored"
    with pytest.raises(RecoveryWorkLimitExceeded) as raised:
        execute_recovery(
            RecoveryRequest(
                frames=tuple(frames),
                passphrase="test passphrase",
                allow_unsigned=True,
                extension_index=0,
                output_path=destination,
            )
        )
    assert raised.value.memory_bytes > 2 * 1024**3
    assert not destination.exists()
