"""Workflow entry points preserve canonical inputs through preparation and execution."""

from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest

from ethernity.config.paths import DEFAULT_CONFIG_PATH
from ethernity.workflows import execution
from ethernity.workflows.backup import service as backup_service
from ethernity.workflows.recovery.planning import normalize_recovery_request
from ethernity.workflows.shared import requests


@pytest.mark.parametrize(
    ("workflow_request", "entry_point", "service_name"),
    (
        (requests.BackupRequest(debug=True, sealed=True), "execute_backup", "prepare_backup_run"),
        (
            requests.RecoveryRequest(extension_index=2, allow_unsigned=True),
            "execute_recovery",
            "prepare_recover_plan",
        ),
        (
            requests.RebuildRequest(allow_stale_head=True),
            "execute_rebuild",
            "execute_rebuild_operation",
        ),
        (
            requests.ReplacementRecoveryRequest(output_dir_existing_parent=True),
            "execute_replacement_recovery",
            "execute_replacement_recovery_operation",
        ),
        (requests.BackupRequest(), "prepare_backup", "prepare_backup_run"),
        (requests.RecoveryRequest(), "inspect_recovery", "inspect_from_request"),
    ),
)
def test_execution_accepts_the_same_request_as_its_service(
    workflow_request, entry_point: str, service_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = SimpleNamespace(
        qr_path="backup.pdf",
        recovery_path="recovery.pdf",
        shard_paths=(),
        signing_key_shard_paths=(),
        kit_index_path=None,
        signing_key_preserved=True,
        doc_hash=b"D" * 32,
        written_paths=(),
        trust_basis="internally_consistent",
        signing_key_verified=False,
        config=None,
        plan=None,
        input_files=(),
        input_origin="file",
        input_roots=(),
    )
    received = []

    def prepare_or_execute(value):
        received.append(value)
        return result

    monkeypatch.setattr(execution, service_name, prepare_or_execute)
    monkeypatch.setattr(execution, "execute_prepared_backup", lambda prepared: prepared)
    monkeypatch.setattr(execution, "execute_recover_plan", lambda plan, **options: plan)
    getattr(execution, entry_point)(workflow_request)

    assert received == [workflow_request]
    assert received[0] is workflow_request


def test_backup_preparation_retains_paths_and_execution_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("example")
    request = requests.BackupRequest(
        config_path=DEFAULT_CONFIG_PATH,
        input_paths=(source,),
        base_dir=tmp_path,
        output_dir=tmp_path / "output",
        layout_debug_dir=tmp_path / "layout",
        sealed=True,
        debug=True,
        debug_max_bytes=4096,
        debug_reveal_secrets=True,
        quiet=True,
    )
    prepared = backup_service.prepare_backup_run(request)
    assert prepared.request is request
    assert prepared.plan.sealed
    assert prepared.input_files[0].data == b"example"
    assert prepared.base_dir == tmp_path

    received = {}
    result = object()

    def generate(**options):
        received.update(options)
        return result

    monkeypatch.setattr(backup_service, "_run_backup", generate)
    assert backup_service.execute_prepared_backup(prepared) is result
    assert received["output_dir"] == request.output_dir
    assert received["layout_debug_dir"] == request.layout_debug_dir
    assert received["debug"] is True
    assert received["debug_max_bytes"] == 4096
    assert received["debug_reveal_secrets"] is True
    assert received["quiet"] is True


def test_recovery_normalizes_fingerprints_without_changing_the_callers_request() -> None:
    request = requests.RecoveryRequest(
        extension_doc_hash="  " + "AB" * 32 + "  ",
        expected_head_doc_hash="CD" * 32,
        scan_paths=(Path("backup"),),
    )
    normalized = normalize_recovery_request(request)

    assert normalized.extension_doc_hash == "ab" * 32
    assert normalized.expected_head_doc_hash == "cd" * 32
    assert normalized.scan_paths is request.scan_paths
    assert request.extension_doc_hash == "  " + "AB" * 32 + "  "
    assert request.expected_head_doc_hash == "CD" * 32
    assert normalize_recovery_request(normalized) is normalized
    with pytest.raises(FrozenInstanceError):
        request.extension_doc_hash = "ef" * 32


@pytest.mark.parametrize(
    "inputs",
    (
        {"extension_doc_hash": "short"},
        {"expected_head_doc_hash": "zz" * 32},
        {"extension_index": 1, "extension_doc_hash": "ab" * 32},
        {"auth_text_file": Path("auth.txt"), "auth_payloads_file": Path("auth.bin")},
        {"extension_doc_hash": "AB" * 32, "expected_head_doc_hash": "invalid"},
    ),
)
def test_invalid_recovery_requests_fail_without_mutation(inputs) -> None:
    request = requests.RecoveryRequest(**inputs)
    with pytest.raises(ValueError):
        normalize_recovery_request(request)
    for name, value in inputs.items():
        assert getattr(request, name) == value
