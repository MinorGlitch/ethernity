from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from ethernity.workflows.add_files.execution import (
    AssessedAddFilesRun,
    assess_prepared_add_files,
    execute_assessed_add_files,
)
from ethernity.workflows.add_files.request import AddFilesRequest


@dataclass(frozen=True)
class _PreparedRequest:
    request: AddFilesRequest


def test_assessment_preflights_and_encrypts_without_rendering(monkeypatch) -> None:
    prepared = SimpleNamespace()
    output_settings = SimpleNamespace()
    encrypted = SimpleNamespace(ciphertext=b"reviewed", built=object())
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        "ethernity.workflows.add_files.execution.add_files_output_settings.resolve_add_files_output_settings",
        lambda value, **kwargs: (
            calls.append(("output_settings", (value, kwargs))) or output_settings
        ),
    )
    monkeypatch.setattr(
        "ethernity.workflows.add_files.execution._preflight_prepared_extension_publish_target",
        lambda value: calls.append(("preflight", value)),
    )
    monkeypatch.setattr(
        "ethernity.workflows.add_files.execution.encrypt_prepared_extension_document",
        lambda value: calls.append(("encrypt", value)) or encrypted,
    )
    monkeypatch.setattr(
        "ethernity.workflows.add_files.execution.require_rebuildable_result",
        lambda value, candidate: calls.append(("capacity", (value, candidate))),
    )
    assessed = assess_prepared_add_files(prepared)

    assert assessed.prepared is prepared
    assert assessed.output_settings is output_settings
    assert assessed.encrypted is encrypted
    assert [name for name, _value in calls] == [
        "output_settings",
        "preflight",
        "encrypt",
        "capacity",
    ]


def test_assessed_execution_publishes_the_exact_reviewed_payload(monkeypatch) -> None:
    prepared = _PreparedRequest(request=AddFilesRequest(config_path="mutable-config.toml"))
    output_settings = SimpleNamespace()
    encrypted = SimpleNamespace(ciphertext=b"reviewed", built=object())
    assessed = AssessedAddFilesRun(
        prepared=prepared,
        output_settings=output_settings,
        encrypted=encrypted,
    )
    calls: list[tuple[str, object]] = []
    executed = SimpleNamespace(result=SimpleNamespace())

    monkeypatch.setattr(
        "ethernity.workflows.add_files.execution._preflight_prepared_extension_publish_target",
        lambda value: calls.append(("preflight", value)),
    )
    monkeypatch.setattr(
        "ethernity.workflows.add_files.execution.require_rebuildable_result",
        lambda value, candidate: calls.append(("capacity", (value, candidate))),
    )

    def fake_execute(value, **kwargs):
        calls.append(("execute", (value, kwargs)))
        return executed

    monkeypatch.setattr(
        "ethernity.workflows.add_files.execution._execute_resolved_add_files",
        fake_execute,
    )

    result = execute_assessed_add_files(
        assessed,
        config_path="reviewed-config.toml",
        nonce="nonce",
    )

    assert result is executed
    preflight_prepared = calls[0][1]
    assert preflight_prepared.request.config_path == "reviewed-config.toml"
    assert calls[1] == ("capacity", (preflight_prepared, encrypted.built))
    value, kwargs = calls[2][1]
    assert value is preflight_prepared
    assert kwargs["output_settings"] is output_settings
    assert kwargs["encrypted"] is encrypted
    assert "chunker" not in kwargs
    assert kwargs["nonce"] == "nonce"
