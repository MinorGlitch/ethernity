from __future__ import annotations

from pathlib import Path

from ethernity.tasks.file_summary import display_path, format_count
from ethernity.tasks.recovery_material import UnlockMaterial

__all__ = [
    "auth_material_control_value",
    "auth_material_summary",
    "non_empty_line_count",
    "pasted_text_summary",
    "recovery_text_summary",
    "unlock_material_summary",
]


def unlock_material_summary(material: UnlockMaterial) -> str:
    if material.passphrase:
        return "Passphrase"
    if material.recovery_documents:
        return format_count(len(material.recovery_documents), "recovery sheet")
    if material.recovery_payload_files:
        return format_count(len(material.recovery_payload_files), "recovery payload file")
    return "Choose an unlock method"


def auth_material_summary(auth_text_file: Path | None, auth_payloads_file: Path | None) -> str:
    if auth_text_file is not None:
        return f"Signature text: {display_path(auth_text_file)}"
    if auth_payloads_file is not None:
        return f"Signature payload: {display_path(auth_payloads_file)}"
    return "Loaded backup"


def auth_material_control_value(
    auth_text_file: object | None,
    auth_payloads_file: object | None,
) -> str:
    if auth_text_file is not None:
        return "text"
    if auth_payloads_file is not None:
        return "payloads"
    return "auto"


def non_empty_line_count(value: str | None) -> int:
    return sum(1 for line in (value or "").splitlines() if line.strip())


def pasted_text_summary(value: str | None) -> str:
    line_count = non_empty_line_count(value)
    noun = "line" if line_count == 1 else "lines"
    return f"Pasted text, {line_count} non-empty {noun}"


def recovery_text_summary(value: str | None) -> str:
    if not value:
        return "Pasted recovery text"
    line_count = non_empty_line_count(value)
    noun = "line" if line_count == 1 else "lines"
    return f"Pasted recovery text: {line_count} {noun}"
