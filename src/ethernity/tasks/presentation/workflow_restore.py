from __future__ import annotations

from ethernity.tasks.presentation.models import (
    WorkspaceAction,
    WorkspaceGroup,
    WorkspaceValue,
)
from ethernity.tasks.presentation.recovery import (
    signature_source_control_value,
    signature_source_summary,
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
                    "signature-source",
                    "Verification source",
                    signature_source_summary(state.auth_text_file, state.auth_payloads_file),
                    control_value=signature_source_control_value(
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
                    "Set latest fingerprint...",
                ),
            ),
        ),
    )
