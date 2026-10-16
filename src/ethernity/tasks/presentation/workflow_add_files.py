from __future__ import annotations

from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.file_summary import selected_items_summary
from ethernity.tasks.models import TaskExecutionPlan, TaskSection
from ethernity.tasks.presentation.models import (
    ReviewDetail,
    WorkspaceAction,
    WorkspaceGroup,
    WorkspaceValue,
)
from ethernity.tasks.presentation.presentation_values import (
    advanced_fields_group,
    base_directory_value,
    qr_density_value,
    signature_source_value,
)
from ethernity.tasks.presentation.recovery import recovery_source_summary, unlock_input_summary
from ethernity.tasks.presentation.review_values import (
    destination_summary,
)


def add_files_auxiliary_groups(
    state: AddFilesTaskState,
    advanced_section: TaskSection,
) -> tuple[WorkspaceGroup, ...]:
    """Build the add-files controls that live outside the typed guided workflow."""

    mode = state.resolved_update_mode()
    source = state.current_source_assessment()
    mode_locked = source is not None and source.has_updates
    return (
        advanced_fields_group(
            advanced_section,
            values=(
                WorkspaceValue(
                    "update-mode",
                    "Update mode",
                    state.update_mode_summary(),
                    control_value=mode.value if mode is not None else "cumulative",
                ),
                WorkspaceValue(
                    "update-mode-locked",
                    "Existing series",
                    "yes" if mode_locked else "no",
                    control_value="locked" if mode_locked else "editable",
                ),
                base_directory_value(state.base_dir),
                qr_density_value(state.qr_chunk_size),
                signature_source_value(state.auth_text_file, state.auth_payloads_file),
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
        ),
    )


def review_details(
    state: AddFilesTaskState,
    plan: TaskExecutionPlan,
) -> tuple[ReviewDetail, ...]:
    source = recovery_source_summary(state)
    changes = (
        f"{selected_items_summary(len(state.input_paths), len(state.input_dirs))}, "
        "replacing matching paths"
    )
    source_version = (
        "Will check trusted fingerprint"
        if state.expected_head_doc_hash is not None
        else "Newest loaded version accepted"
    )

    return (
        ReviewDetail("Backup", source, "source"),
        ReviewDetail("Changes", changes, "files"),
        ReviewDetail("Source version", source_version, "freshness"),
        ReviewDetail("Unlock", unlock_input_summary(state), "unlock"),
        ReviewDetail("Recovery sheets", state.recovery_sheet_summary(), "recovery"),
        ReviewDetail("Documents", "Update PDF\nRecovery guide", group="output"),
        ReviewDetail("Destination", destination_summary(plan), "output", "output"),
    )
