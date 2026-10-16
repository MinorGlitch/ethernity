from __future__ import annotations

from dataclasses import replace
from typing import Literal

import pytest

from ethernity.workflows.replacement_recovery import service as replacement_service
from ethernity.workflows.shared.backup_validation import validate_backup_request
from ethernity.workflows.shared.requests import BackupRequest, ReplacementRecoveryRequest

Operation = Literal["backup", "replacement", "inspection"]


def _validate_quorum(
    operation: Operation, signing: bool, threshold: int | None, count: int | None
) -> None:
    if operation == "backup":
        backup = BackupRequest(
            shard_threshold=2,
            shard_count=3,
            signing_key_mode="sharded" if signing else "embedded",
        )
        if signing:
            backup = replace(
                backup, signing_key_shard_threshold=threshold, signing_key_shard_count=count
            )
        else:
            backup = replace(backup, shard_threshold=threshold, shard_count=count)
        validate_backup_request(backup)
        return

    replacement = ReplacementRecoveryRequest(
        payloads_file="backup.txt",
        passphrase="passphrase",
        shard_threshold=2,
        shard_count=3,
        create_passphrase_shards=not signing,
        create_signing_key_shards=signing,
    )
    if signing:
        replacement = replace(
            replacement, signing_key_shard_threshold=threshold, signing_key_shard_count=count
        )
    else:
        replacement = replace(replacement, shard_threshold=threshold, shard_count=count)
    replacement_service._validate_replacement_args(
        replacement, require_output_configuration=operation != "inspection"
    )


@pytest.mark.parametrize("operation", ["backup", "replacement", "inspection"])
@pytest.mark.parametrize("signing", [False, True])
@pytest.mark.parametrize("threshold,count", [(1, 1), (1, 255), (2, 3), (255, 255)])
def test_workflow_quorum_accepts_valid_bounds(
    operation: Operation, signing: bool, threshold: int, count: int
) -> None:
    _validate_quorum(operation, signing, threshold, count)


@pytest.mark.parametrize("operation", ["backup", "replacement", "inspection"])
@pytest.mark.parametrize("signing", [False, True])
@pytest.mark.parametrize(
    "threshold,count,reason",
    [
        (0, 3, "threshold must be >= 1"),
        (-1, 3, "threshold must be >= 1"),
        (256, 256, "threshold must be <= 255"),
        (2, 0, "count must be >="),
        (3, 2, "count must be >="),
        (2, 256, "count must be <= 255"),
    ],
)
def test_workflow_quorum_rejects_invalid_bounds(
    operation: Operation, signing: bool, threshold: int, count: int, reason: str
) -> None:
    prefix = "shard"
    if signing:
        prefix = "signing key shard" if operation == "backup" else "signing-key shard"
    expected = f"{prefix} {reason}"
    if reason == "count must be >=":
        expected += f" {prefix} threshold"
    with pytest.raises(ValueError) as failure:
        _validate_quorum(operation, signing, threshold, count)
    assert str(failure.value) == expected


@pytest.mark.parametrize("operation", ["backup", "replacement", "inspection"])
@pytest.mark.parametrize("signing", [False, True])
@pytest.mark.parametrize("threshold,count", [(None, 3), (2, None)])
def test_workflow_quorum_requires_both_values_when_either_is_supplied(
    operation: Operation, signing: bool, threshold: int | None, count: int | None
) -> None:
    flag = "signing-key-shard" if signing else "shard"
    with pytest.raises(ValueError) as failure:
        _validate_quorum(operation, signing, threshold, count)
    assert str(failure.value) == f"both --{flag}-threshold and --{flag}-count are required"


@pytest.mark.parametrize("operation", ["backup", "replacement", "inspection"])
@pytest.mark.parametrize("signing", [False, True])
def test_workflow_quorum_absence_depends_on_operation(operation: Operation, signing: bool) -> None:
    if operation == "replacement" and not signing:
        with pytest.raises(ValueError) as failure:
            _validate_quorum(operation, signing, None, None)
        assert str(failure.value) == "--shard-threshold and --shard-count are required"
    else:
        _validate_quorum(operation, signing, None, None)


@pytest.mark.parametrize(
    "threshold,count,message",
    [
        (None, 3, "both --signing-key-shard-threshold and --signing-key-shard-count are required"),
        (0, 3, "signing key shard quorum requires --signing-key-mode sharded"),
    ],
)
def test_backup_signing_mode_validation_preserves_error_order(
    threshold: int | None, count: int, message: str
) -> None:
    request = BackupRequest(
        signing_key_mode="embedded",
        signing_key_shard_threshold=threshold,
        signing_key_shard_count=count,
    )
    with pytest.raises(ValueError) as failure:
        validate_backup_request(request)
    assert str(failure.value) == message


def test_backup_signing_shards_require_passphrase_sharding() -> None:
    with pytest.raises(ValueError, match="signing key sharding requires passphrase sharding"):
        validate_backup_request(BackupRequest(signing_key_mode="sharded"))


def test_replacement_signing_shards_require_a_quorum() -> None:
    request = ReplacementRecoveryRequest(
        payloads_file="backup.txt",
        passphrase="passphrase",
        create_passphrase_shards=False,
        create_signing_key_shards=True,
    )
    with pytest.raises(ValueError, match="creating signing-key shards requires a shard quorum"):
        replacement_service._validate_replacement_args(request)
    replacement_service._validate_replacement_args(request, require_output_configuration=False)


def test_compatible_replacement_uses_existing_shard_quorum() -> None:
    request = ReplacementRecoveryRequest(
        payloads_file="backup.txt",
        passphrase="passphrase",
        shard_text_files=("old-shard.txt",),
        passphrase_replacement_count=1,
        create_signing_key_shards=False,
    )
    replacement_service._validate_replacement_args(request)
