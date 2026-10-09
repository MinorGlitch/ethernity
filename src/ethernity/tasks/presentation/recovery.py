from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ethernity.tasks.file_summary import display_path, format_count
from ethernity.tasks.recovery_inputs import UnlockInputs, detected_unlock_summary

if TYPE_CHECKING:
    from ethernity.tasks.source_assessment import ContentRecoveryTaskState

__all__ = [
    "signature_source_control_value",
    "signature_source_summary",
    "non_empty_line_count",
    "pasted_text_summary",
    "recovery_text_summary",
    "unlock_input_summary",
    "recovery_source_summary",
]


def unlock_input_summary(inputs: UnlockInputs) -> str:
    if inputs.passphrase:
        return "Passphrase"
    if inputs.recovery_documents:
        return format_count(len(inputs.recovery_documents), "recovery sheet")
    if inputs.recovery_payload_files:
        return format_count(len(inputs.recovery_payload_files), "recovery payload file")
    if (detected := detected_unlock_summary(inputs)) is not None:
        return detected
    return "Choose an unlock method"


def signature_source_summary(auth_text_file: Path | None, auth_payloads_file: Path | None) -> str:
    if auth_text_file is not None:
        return f"Signature text: {display_path(auth_text_file)}"
    if auth_payloads_file is not None:
        return f"Signature payload: {display_path(auth_payloads_file)}"
    return "Loaded backup"


def signature_source_control_value(
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


def recovery_source_summary(state: ContentRecoveryTaskState) -> str:
    request = state.source_assessment_request()
    if request is not None and request.source_kind == "recovery_inputs":
        return "Mixed backup documents"
    if state.source_paths:
        return format_count(len(state.source_paths), "document input")
    if state.recovery_text:
        return "Pasted recovery text"
    if state.recovery_text_file is not None:
        return "Recovery text file"
    return "Backup payload file"
