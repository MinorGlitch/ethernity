from __future__ import annotations

from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.file_summary import display_path
from ethernity.tasks.models import TaskSection
from ethernity.tasks.presentation.common import (
    qr_chunk_size_control_value,
    qr_chunk_size_summary,
)
from ethernity.tasks.presentation.models import (
    WorkspaceAction,
    WorkspaceGroup,
    WorkspaceValue,
)


def add_files_auxiliary_groups(
    state: AddFilesTaskState,
    advanced_section: TaskSection,
) -> tuple[WorkspaceGroup, ...]:
    """Build the add-files controls that live outside the typed guided workflow."""

    return (
        WorkspaceGroup(
            key="advanced",
            title="Advanced",
            kind="fields",
            values=(
                WorkspaceValue(
                    "base-dir",
                    "Base folder",
                    display_path(state.base_dir)
                    if state.base_dir is not None
                    else "Based on selected files",
                    control_value="custom" if state.base_dir is not None else "automatic",
                ),
                WorkspaceValue(
                    "qr-chunk-size",
                    "QR density",
                    qr_chunk_size_summary(state.qr_chunk_size),
                    control_value=qr_chunk_size_control_value(state.qr_chunk_size),
                ),
                WorkspaceValue(
                    "unlock-policy",
                    "Recovery scope",
                    add_files_unlock_policy_summary(state),
                    control_value=state.unlock_policy or "default",
                ),
                WorkspaceValue(
                    "recovery-docs",
                    "Recovery sheets",
                    add_files_recovery_summary(state),
                    control_value=add_files_recovery_control_value(state),
                ),
                WorkspaceValue(
                    "signing-key",
                    "Signing-key recovery",
                    add_files_signing_key_summary(state),
                    control_value=add_files_signing_key_control_value(state),
                ),
            ),
            actions=(
                WorkspaceAction("workspace-add-files-base-dir", "Choose base folder..."),
                WorkspaceAction("workspace-add-files-qr-chunk-size", "Set QR density..."),
            ),
            status=advanced_section.status,
            status_summary=advanced_section.summary,
        ),
    )


def add_files_unlock_policy_summary(state: AddFilesTaskState) -> str:
    if state.unlock_policy is None:
        return "From settings"
    if state.unlock_policy == "reuse-root":
        return "Reuse original recovery"
    return "Self-contained update"


def add_files_recovery_summary(state: AddFilesTaskState) -> str:
    if state.recovery_document_count == 0:
        return "No new recovery sheets"
    if state.recovery_document_threshold is not None and state.recovery_document_count is not None:
        return (
            f"{state.recovery_document_count} recovery sheets; "
            f"any {state.recovery_document_threshold} required"
        )
    return "From settings"


def add_files_recovery_control_value(state: AddFilesTaskState) -> str:
    if state.recovery_document_count == 0:
        return "none"
    if state.recovery_document_threshold is not None and state.recovery_document_count is not None:
        return "custom"
    return "default"


def add_files_signing_key_summary(state: AddFilesTaskState) -> str:
    if state.signing_key_mode is None:
        return "From settings"
    if state.signing_key_mode == "not-stored":
        return "No separate key sheets"
    if (
        state.signing_key_recovery_threshold is not None
        and state.signing_key_recovery_count is not None
    ):
        return (
            f"{state.signing_key_recovery_count} key sheets; "
            f"any {state.signing_key_recovery_threshold} can recover the key"
        )
    return "Separate key sheets"


def add_files_signing_key_control_value(state: AddFilesTaskState) -> str:
    if state.signing_key_mode is None:
        return "default"
    if state.signing_key_mode == "not-stored":
        return "not-stored"
    if (
        state.signing_key_recovery_threshold is not None
        and state.signing_key_recovery_count is not None
    ):
        return "custom"
    return "sharded"
