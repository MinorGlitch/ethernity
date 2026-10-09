from __future__ import annotations

from ethernity.tasks.file_summary import format_count
from ethernity.tasks.models import TaskExecutionPlan, TaskSection
from ethernity.tasks.presentation.models import (
    ReviewDetail,
    WorkspaceAction,
    WorkspaceGroup,
    WorkspaceValue,
)
from ethernity.tasks.presentation.presentation_values import (
    advanced_fields_group,
    qr_density_value,
    signature_source_value,
)
from ethernity.tasks.presentation.recovery import unlock_input_summary
from ethernity.tasks.presentation.review_values import (
    destination_summary,
    layout_summary,
)
from ethernity.tasks.rebuild import RebuildTaskState


def rebuild_auxiliary_groups(
    state: RebuildTaskState,
    advanced_section: TaskSection,
) -> tuple[WorkspaceGroup, ...]:
    """Build the rebuild controls that live outside the typed guided workflow."""

    source_loaded = state.backup_folder is not None or bool(state.source_paths)
    return (
        advanced_fields_group(
            advanced_section,
            values=(
                signature_source_value(
                    state.auth_text_file, state.auth_payloads_file, source_loaded=source_loaded
                ),
                qr_density_value(state.qr_chunk_size),
                WorkspaceValue(
                    "source-status",
                    "Backup state",
                    "Loaded backup" if source_loaded else "No backup loaded",
                    control_value="loaded" if source_loaded else "empty",
                ),
            ),
            actions=(WorkspaceAction("workspace-rebuild-qr-chunk-size", "Set QR density..."),),
        ),
    )


def review_details(
    state: RebuildTaskState,
    plan: TaskExecutionPlan,
) -> tuple[ReviewDetail, ...]:
    source = (
        "Existing backup folder"
        if state.backup_folder is not None
        else format_count(len(state.source_paths), "document input")
    )
    if state.expected_head_doc_hash is not None:
        source_version = "Will check trusted fingerprint"
    else:
        source_version = "Latest loaded version accepted"
    return (
        ReviewDetail("Source", source, "source"),
        ReviewDetail("Recovery sheets", "Follow the loaded backup's sheet policy"),
        ReviewDetail("Unlock", unlock_input_summary(state), "unlock"),
        ReviewDetail("Source version", source_version, "freshness"),
        ReviewDetail("Documents", "Backup PDF\nRecovery guide", group="output"),
        ReviewDetail("Layout", layout_summary(state.paper_size, state.design), "layout", "output"),
        ReviewDetail("Destination", destination_summary(plan), "output", "output"),
    )
