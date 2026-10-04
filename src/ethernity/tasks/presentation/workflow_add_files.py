from __future__ import annotations

from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.file_summary import display_path
from ethernity.tasks.models import TaskSection
from ethernity.tasks.presentation.models import (
    WorkspaceAction,
    WorkspaceGroup,
    WorkspaceValue,
)
from ethernity.tasks.presentation.presentation_values import (
    qr_chunk_size_control_value,
    qr_chunk_size_summary,
)
from ethernity.tasks.presentation.recovery import (
    signature_source_control_value,
    signature_source_summary,
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
                    "signature-source",
                    "Verification source",
                    signature_source_summary(state.auth_text_file, state.auth_payloads_file),
                    control_value=signature_source_control_value(
                        state.auth_text_file, state.auth_payloads_file
                    ),
                ),
                WorkspaceValue(
                    "recovery-sheets",
                    "New recovery sheets",
                    state.recovery_sheet_summary(),
                    control_value="create" if state.create_recovery_sheets else "off",
                ),
            ),
            actions=(
                WorkspaceAction("workspace-add-files-base-dir", "Choose base folder..."),
                WorkspaceAction("workspace-add-files-qr-chunk-size", "Set QR density..."),
                WorkspaceAction(
                    "workspace-add-files-recovery-sheets",
                    "Configure recovery sheets...",
                ),
            ),
            status=advanced_section.status,
            status_summary=advanced_section.summary,
        ),
    )
