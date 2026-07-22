from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ethernity.tasks.presentation.recovery import (
    auth_material_control_value,
    auth_material_summary,
    pasted_text_summary,
    recovery_text_summary,
    unlock_material_summary,
)
from ethernity.tasks.recovery_material import (
    has_recovery_source,
    has_unlock_material,
    recovery_text_error,
    recovery_text_frames,
)


@dataclass
class _Material:
    passphrase: str | None = None
    recovery_documents: list[Path] = field(default_factory=list)
    recovery_payload_files: list[Path] = field(default_factory=list)


@dataclass
class _SourceMaterial:
    source_paths: list[Path] = field(default_factory=list)
    recovery_text: str | None = None
    recovery_text_file: Path | None = None
    payloads_file: Path | None = None


def test_unlock_material_helpers_preserve_precedence_and_counts() -> None:
    material = _Material(
        passphrase="secret",
        recovery_documents=[Path("one.pdf"), Path("two.pdf")],
        recovery_payload_files=[Path("payload.txt")],
    )

    assert has_unlock_material(material)
    assert unlock_material_summary(material) == "Passphrase"

    material.passphrase = None
    assert unlock_material_summary(material) == "2 recovery sheets"

    material.recovery_documents.clear()
    assert unlock_material_summary(material) == "1 recovery payload file"

    material.recovery_payload_files.clear()
    assert not has_unlock_material(material)
    assert unlock_material_summary(material) == "Choose an unlock method"


def test_recovery_source_material_accepts_each_supported_source() -> None:
    assert not has_recovery_source(_SourceMaterial())
    assert has_recovery_source(_SourceMaterial(source_paths=[Path("scan.png")]))
    assert has_recovery_source(_SourceMaterial(recovery_text="frame"))
    assert has_recovery_source(_SourceMaterial(recovery_text_file=Path("fallback.txt")))
    assert has_recovery_source(_SourceMaterial(payloads_file=Path("payloads.txt")))


def test_recovery_presentation_helpers_preserve_user_facing_text() -> None:
    assert auth_material_summary(Path("signature.txt"), None) == "Signature text: signature.txt"
    assert auth_material_summary(None, Path("payloads.txt")) == ("Signature payload: payloads.txt")
    assert auth_material_control_value(None, None) == "auto"
    assert auth_material_control_value(object(), None) == "text"
    assert auth_material_control_value(None, object()) == "payloads"
    assert pasted_text_summary("one\n\n two\n") == "Pasted text, 2 non-empty lines"
    assert recovery_text_summary(None) == "Pasted recovery text"
    assert recovery_text_summary("one") == "Pasted recovery text: 1 line"
    assert recovery_text_summary("one\n\ntwo") == "Pasted recovery text: 2 lines"


def test_recovery_text_helpers_share_empty_and_invalid_input_handling() -> None:
    assert recovery_text_frames(None, quiet=True) is None
    assert recovery_text_error(None) is None
    assert recovery_text_error("not recovery text") is not None
