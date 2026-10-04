from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ethernity.tasks.presentation.recovery import (
    pasted_text_summary,
    recovery_text_summary,
    signature_source_control_value,
    signature_source_summary,
    unlock_input_summary,
)
from ethernity.tasks.recovery_inputs import (
    has_recovery_source,
    has_unlock_inputs,
    recovery_text_error,
    recovery_text_frames,
)


@dataclass
class _UnlockInputs:
    passphrase: str | None = None
    recovery_documents: list[Path] = field(default_factory=list)
    recovery_payload_files: list[Path] = field(default_factory=list)


@dataclass
class _RecoveryInputs:
    source_paths: list[Path] = field(default_factory=list)
    recovery_text: str | None = None
    recovery_text_file: Path | None = None
    payloads_file: Path | None = None


def test_unlock_input_summary_preserves_precedence_and_counts() -> None:
    inputs = _UnlockInputs(
        passphrase="secret",
        recovery_documents=[Path("one.pdf"), Path("two.pdf")],
        recovery_payload_files=[Path("payload.txt")],
    )

    assert has_unlock_inputs(inputs)
    assert unlock_input_summary(inputs) == "Passphrase"

    inputs.passphrase = None
    assert unlock_input_summary(inputs) == "2 recovery sheets"

    inputs.recovery_documents.clear()
    assert unlock_input_summary(inputs) == "1 recovery payload file"

    inputs.recovery_payload_files.clear()
    assert not has_unlock_inputs(inputs)
    assert unlock_input_summary(inputs) == "Choose an unlock method"


def test_recovery_source_inputs_accepts_each_supported_source() -> None:
    assert not has_recovery_source(_RecoveryInputs())
    assert has_recovery_source(_RecoveryInputs(source_paths=[Path("scan.png")]))
    assert has_recovery_source(_RecoveryInputs(recovery_text="frame"))
    assert has_recovery_source(_RecoveryInputs(recovery_text_file=Path("fallback.txt")))
    assert has_recovery_source(_RecoveryInputs(payloads_file=Path("payloads.txt")))


def test_recovery_presentation_preserves_user_facing_text() -> None:
    assert signature_source_summary(Path("signature.txt"), None) == "Signature text: signature.txt"
    assert signature_source_summary(None, Path("payloads.txt")) == (
        "Signature payload: payloads.txt"
    )
    assert signature_source_control_value(None, None) == "auto"
    assert signature_source_control_value(object(), None) == "text"
    assert signature_source_control_value(None, object()) == "payloads"
    assert pasted_text_summary("one\n\n two\n") == "Pasted text, 2 non-empty lines"
    assert recovery_text_summary(None) == "Pasted recovery text"
    assert recovery_text_summary("one") == "Pasted recovery text: 1 line"
    assert recovery_text_summary("one\n\ntwo") == "Pasted recovery text: 2 lines"


def test_recovery_text_parsers_share_empty_and_invalid_input_handling() -> None:
    assert recovery_text_frames(None, quiet=True) is None
    assert recovery_text_error(None) is None
    assert recovery_text_error("not recovery text") is not None
