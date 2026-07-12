from __future__ import annotations

from ethernity.tasks.file_summary import format_count
from ethernity.tasks.models import TaskSection
from ethernity.tasks.presentation.models import (
    WorkspaceAction,
    WorkspaceChoice,
    WorkspaceGroup,
    WorkspaceValue,
)
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState


def replace_recovery_auxiliary_groups(
    state: ReplaceRecoveryDocsTaskState,
    signature_section: TaskSection,
) -> tuple[WorkspaceGroup, ...]:
    """Build replacement controls that live outside the typed guided workflow."""

    return (
        WorkspaceGroup(
            key="signing-key-recovery",
            title="Signing-key sheets",
            kind="radio",
            values=(
                WorkspaceValue(
                    "signing-key",
                    "Key sheets",
                    replace_signing_key_recovery_summary(state),
                ),
                WorkspaceValue(
                    "signing-key-payloads",
                    "Existing key payloads",
                    state.signing_key_recovery_payloads_summary(),
                ),
            ),
            choices=(
                WorkspaceChoice(
                    "off",
                    "Do not create signing-key recovery sheets",
                    not state._creates_signing_key_recovery(),
                ),
                WorkspaceChoice(
                    "same",
                    "Match recovery-sheet quorum",
                    state.mint_signing_key_recovery
                    and state.signing_key_recovery_threshold is None
                    and state.signing_key_recovery_count is None
                    and state.signing_key_replacement_count is None,
                ),
                WorkspaceChoice(
                    "custom",
                    "Custom quorum",
                    (
                        state.signing_key_recovery_threshold is not None
                        or state.signing_key_recovery_count is not None
                    ),
                ),
                WorkspaceChoice(
                    "replace",
                    "Replace existing key sheets",
                    state.signing_key_replacement_count is not None,
                ),
            ),
            actions=(
                WorkspaceAction("workspace-replace-signing-key-quorum", "Set quorum..."),
                WorkspaceAction("workspace-replace-signing-key-count", "Set count..."),
                WorkspaceAction("workspace-replace-signing-key-payloads", "Load key payloads..."),
            ),
            status=signature_section.status,
            status_summary=signature_section.summary,
        ),
    )


def replace_signing_key_recovery_summary(state: ReplaceRecoveryDocsTaskState) -> str:
    if not state._creates_signing_key_recovery():
        return "No separate key sheets"
    if state.signing_key_replacement_count is not None:
        return format_count(state.signing_key_replacement_count, "replacement sheet")
    threshold = state.signing_key_recovery_threshold or state.recovery_threshold
    count = state.signing_key_recovery_count or state.recovery_document_count
    return f"{count} key sheets; any {threshold} can recover the key"
