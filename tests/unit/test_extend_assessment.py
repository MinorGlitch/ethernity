from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from ethernity.workflows.extension.execution import (
    AssessedExtendRun,
    assess_prepared_extend,
    execute_assessed_extend,
)
from ethernity.workflows.extension.request import ExtensionRequest


@dataclass(frozen=True)
class _PreparedWithArgs:
    args: ExtensionRequest


def test_assessment_preflights_encrypts_and_render_validates_once(monkeypatch) -> None:
    prepared = SimpleNamespace()
    runtime = SimpleNamespace()
    encrypted = SimpleNamespace(ciphertext=b"reviewed")
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        "ethernity.workflows.extension.execution._runtime_impl.resolve_extend_runtime",
        lambda value, **kwargs: calls.append(("runtime", (value, kwargs))) or runtime,
    )
    monkeypatch.setattr(
        "ethernity.workflows.extension.execution._preflight_prepared_extension_publish_target",
        lambda value: calls.append(("preflight", value)),
    )
    monkeypatch.setattr(
        "ethernity.workflows.extension.execution.encrypt_prepared_extension_document",
        lambda value, *, chunker: calls.append(("encrypt", (value, chunker))) or encrypted,
    )
    monkeypatch.setattr(
        "ethernity.workflows.extension.execution.validate_prepared_extend_render",
        lambda value, *, runtime, encrypted: calls.append(("render", (value, runtime, encrypted))),
    )

    assessed = assess_prepared_extend(prepared)

    assert assessed.prepared is prepared
    assert assessed.runtime is runtime
    assert assessed.encrypted is encrypted
    assert [name for name, _value in calls] == [
        "runtime",
        "preflight",
        "encrypt",
        "render",
    ]


def test_assessed_execution_publishes_the_exact_reviewed_payload(monkeypatch) -> None:
    prepared = _PreparedWithArgs(args=ExtensionRequest(config_path="mutable-config.toml"))
    runtime = SimpleNamespace()
    encrypted = SimpleNamespace(ciphertext=b"reviewed")
    assessed = AssessedExtendRun(
        prepared=prepared,
        runtime=runtime,
        encrypted=encrypted,
    )
    calls: list[tuple[str, object]] = []
    executed = SimpleNamespace(result=SimpleNamespace())

    monkeypatch.setattr(
        "ethernity.workflows.extension.execution._preflight_prepared_extension_publish_target",
        lambda value: calls.append(("preflight", value)),
    )

    def fake_execute(value, **kwargs):
        calls.append(("execute", (value, kwargs)))
        return executed

    monkeypatch.setattr(
        "ethernity.workflows.extension.execution._execute_resolved_extend",
        fake_execute,
    )

    result = execute_assessed_extend(
        assessed,
        config_path="reviewed-config.toml",
        nonce="nonce",
    )

    assert result is executed
    preflight_prepared = calls[0][1]
    assert preflight_prepared.args.config_path == "reviewed-config.toml"
    value, kwargs = calls[1][1]
    assert value is preflight_prepared
    assert kwargs["runtime"] is runtime
    assert kwargs["encrypted"] is encrypted
    assert kwargs["chunker"] is None
    assert kwargs["nonce"] == "nonce"
