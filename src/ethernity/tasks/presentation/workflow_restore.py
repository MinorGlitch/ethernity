from __future__ import annotations

from ethernity.tasks.models import TaskExecutionPlan
from ethernity.tasks.presentation.models import (
    ReviewDetail,
    WorkspaceAction,
    WorkspaceGroup,
    WorkspaceValue,
)
from ethernity.tasks.presentation.presentation_values import signature_source_value
from ethernity.tasks.presentation.recovery import recovery_source_summary, unlock_input_summary
from ethernity.tasks.presentation.review_values import (
    destination_summary,
)
from ethernity.tasks.restore import RestoreTaskState


def restore_auxiliary_groups(state: RestoreTaskState) -> tuple[WorkspaceGroup, ...]:
    """Build the restore controls that live outside the typed guided workflow."""

    return (
        WorkspaceGroup(
            key="authentication",
            title="Verification",
            kind="policy",
            values=(
                WorkspaceValue(
                    "allow-unsigned",
                    "Signature check",
                    "Unsigned legacy backups allowed"
                    if state.allow_unsigned
                    else "Trusted signatures required",
                    control_value="allow-unsigned" if state.allow_unsigned else "require-signed",
                ),
                signature_source_value(state.auth_text_file, state.auth_payloads_file),
            ),
            status_summary=(
                "Unsigned legacy backups allowed"
                if state.allow_unsigned
                else "Trusted signatures required"
            ),
            status="warning" if state.allow_unsigned else "ready",
            actions=(
                WorkspaceAction(
                    "workspace-restore-expected-head",
                    "Set latest fingerprint...",
                ),
            ),
        ),
    )


def review_details(
    state: RestoreTaskState,
    plan: TaskExecutionPlan,
) -> tuple[ReviewDetail, ...]:
    source = recovery_source_summary(state)

    if state.target == "original":
        target = "Initial backup only"
    elif state.target == "specific_update":
        target = (
            f"Update {state.extension_index}"
            if state.extension_index is not None
            else "Specific fingerprint"
        )
    else:
        target = "Newest loaded version"

    signature = (
        "Unsigned legacy backups allowed" if state.allow_unsigned else "Trusted signature required"
    )
    return (
        ReviewDetail("Source", source, "source"),
        ReviewDetail("Files", "All files in the selected backup version"),
        ReviewDetail("Unlock", unlock_input_summary(state), "unlock"),
        ReviewDetail("Version", target, "target"),
        ReviewDetail("Signature", signature, "authentication"),
        ReviewDetail("Destination", destination_summary(plan), "output", "output"),
    )
