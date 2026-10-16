from __future__ import annotations

import base64
from pathlib import Path

import pytest

from ethernity.crypto import age_runtime
from ethernity.crypto.age_policy import (
    MAX_RECOVERY_KDF_WORK,
    MAX_RECOVERY_SCRYPT_LOG_N,
    KdfBudget,
    RecoveryResourceLimitError,
    inspect_age_scrypt_stanza,
    preflight_age_scrypt,
    recovery_kdf_budget,
)
from ethernity.crypto.document_identity import doc_id_and_hash_from_ciphertext
from ethernity.encoding.framing import VERSION, Frame, FrameType
from ethernity.workflows.execution import execute_recovery
from ethernity.workflows.shared.requests import RecoveryRequest


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


@pytest.mark.parametrize("log_n", (18, 19, 20, MAX_RECOVERY_SCRYPT_LOG_N))
def test_supported_profiles_use_one_automatic_policy(log_n: int) -> None:
    document = _synthetic_age_document(log_n)
    with recovery_kdf_budget() as budget:
        profile = preflight_age_scrypt(document)
    assert budget.consumed_work == profile.work
    assert budget.maximum_work == MAX_RECOVERY_KDF_WORK


def test_cumulative_kdf_budget_is_charged_before_work_starts() -> None:
    document = _synthetic_age_document(18)
    budget = KdfBudget(maximum_work=(2**18) * 2)

    preflight_age_scrypt(document, budget=budget)
    preflight_age_scrypt(document, budget=budget)
    with pytest.raises(RecoveryResourceLimitError, match="cumulative scrypt work"):
        preflight_age_scrypt(document, budget=budget)

    assert budget.consumed_work <= MAX_RECOVERY_KDF_WORK


def test_nested_recovery_phases_share_one_cumulative_budget() -> None:
    document = _synthetic_age_document(18)

    with recovery_kdf_budget() as operation_budget:
        preflight_age_scrypt(document)
        with recovery_kdf_budget() as phase_budget:
            preflight_age_scrypt(document)

    assert phase_budget is operation_budget
    assert operation_budget.consumed_work == 2 * (2**18)


def test_cumulative_limit_rejects_work_without_charging_it() -> None:
    document = _synthetic_age_document(MAX_RECOVERY_SCRYPT_LOG_N)
    with recovery_kdf_budget() as budget:
        for _ in range(8):
            preflight_age_scrypt(document)
        with recovery_kdf_budget() as nested:
            with pytest.raises(RecoveryResourceLimitError, match="cumulative scrypt work"):
                preflight_age_scrypt(document)
        assert nested is budget
        assert budget.consumed_work == MAX_RECOVERY_KDF_WORK

    # A separate operation gets a fresh budget; nested phases cannot reset it.
    with recovery_kdf_budget() as fresh:
        preflight_age_scrypt(document)
        assert fresh.consumed_work == 2**MAX_RECOVERY_SCRYPT_LOG_N


def test_rejected_profile_does_not_consume_budget() -> None:
    with recovery_kdf_budget() as budget:
        with pytest.raises(RecoveryResourceLimitError, match="hard limit"):
            preflight_age_scrypt(_synthetic_age_document(MAX_RECOVERY_SCRYPT_LOG_N + 1))
        assert budget.consumed_work == 0


def test_decryption_enforces_limits_before_starting_a_worker(monkeypatch) -> None:
    calls = []

    def decrypt_worker(data, passphrase, profile):
        calls.append(profile.log_n)
        return b"plaintext"

    monkeypatch.setattr(age_runtime, "_decrypt_with_pyrage_worker", decrypt_worker)
    document = _synthetic_age_document(MAX_RECOVERY_SCRYPT_LOG_N)
    with recovery_kdf_budget():
        for _ in range(8):
            assert age_runtime.decrypt_bytes(document, passphrase="secret") == b"plaintext"
        with pytest.raises(RecoveryResourceLimitError, match="cumulative scrypt work"):
            age_runtime.decrypt_bytes(document, passphrase="secret")

    with pytest.raises(RecoveryResourceLimitError, match="hard limit"):
        age_runtime.decrypt_bytes(
            _synthetic_age_document(MAX_RECOVERY_SCRYPT_LOG_N + 1), passphrase="secret"
        )
    assert calls == [MAX_RECOVERY_SCRYPT_LOG_N] * 8


@pytest.mark.parametrize("document_count", (1, 2))
def test_restore_preserves_resource_failure_and_writes_nothing(
    tmp_path: Path, document_count: int
) -> None:
    frames = []
    for index in range(document_count):
        ciphertext = _synthetic_age_document(MAX_RECOVERY_SCRYPT_LOG_N + 1) + bytes([index])
        doc_id, _doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
        frames.append(Frame(VERSION, FrameType.MAIN_DOCUMENT, doc_id, 0, 1, ciphertext))
    destination = tmp_path / "restored"
    with pytest.raises(RecoveryResourceLimitError, match="hard limit"):
        execute_recovery(
            RecoveryRequest(
                frames=tuple(frames),
                passphrase="test passphrase",
                allow_unsigned=True,
                extension_index=0,
                output_path=destination,
            )
        )
    assert not destination.exists()
