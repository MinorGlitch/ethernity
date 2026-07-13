from __future__ import annotations

from ethernity.tasks.presentation.models import (
    WorkspaceAction,
    WorkspaceGroup,
    WorkspaceValue,
)
from ethernity.tasks.presentation.recovery import (
    auth_material_control_value,
    auth_material_summary,
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
                WorkspaceValue(
                    "auth-material",
                    "Verification source",
                    auth_material_summary(state.auth_text_file, state.auth_payloads_file),
                    control_value=auth_material_control_value(
                        state.auth_text_file,
                        state.auth_payloads_file,
                    ),
                ),
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
                    "Set expected latest fingerprint...",
                ),
            ),
        ),
    )
