from __future__ import annotations

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
from ethernity.tasks.presentation.recovery import (
    auth_material_control_value,
    auth_material_summary,
)
from ethernity.tasks.rebuild import RebuildTaskState


def rebuild_auxiliary_groups(
    state: RebuildTaskState,
    advanced_section: TaskSection,
) -> tuple[WorkspaceGroup, ...]:
    """Build the rebuild controls that live outside the typed guided workflow."""

    source_loaded = state.backup_folder is not None or bool(state.source_paths)
    return (
        WorkspaceGroup(
            key="advanced",
            title="Advanced",
            kind="fields",
            values=(
                WorkspaceValue(
                    "auth-material",
                    "Verification source",
                    (
                        auth_material_summary(state.auth_text_file, state.auth_payloads_file)
                        if source_loaded
                        or state.auth_text_file is not None
                        or state.auth_payloads_file is not None
                        else "Choose a backup first"
                    ),
                    control_value=auth_material_control_value(
                        state.auth_text_file,
                        state.auth_payloads_file,
                    ),
                ),
                WorkspaceValue(
                    "qr-chunk-size",
                    "QR density",
                    qr_chunk_size_summary(state.qr_chunk_size),
                    control_value=qr_chunk_size_control_value(state.qr_chunk_size),
                ),
                WorkspaceValue(
                    "source-context",
                    "Backup state",
                    "Loaded backup" if source_loaded else "No backup loaded",
                    control_value="loaded" if source_loaded else "empty",
                ),
            ),
            actions=(WorkspaceAction("workspace-rebuild-qr-chunk-size", "Set QR density..."),),
            status=advanced_section.status,
            status_summary=advanced_section.summary,
        ),
    )
