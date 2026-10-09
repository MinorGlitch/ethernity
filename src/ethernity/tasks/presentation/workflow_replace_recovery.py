from __future__ import annotations

from ethernity.tasks.file_summary import format_count
from ethernity.tasks.models import TaskExecutionPlan, TaskSection
from ethernity.tasks.presentation.models import (
    ChoicePresentation,
    ReviewDetail,
    WorkspaceAction,
    WorkspaceGroup,
    WorkspaceValue,
)
from ethernity.tasks.presentation.recovery import recovery_source_summary, unlock_input_summary
from ethernity.tasks.presentation.review_values import (
    destination_summary,
    layout_summary,
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
                ChoicePresentation(
                    "off",
                    "Do not create signing-key recovery sheets",
                    not state._creates_signing_key_recovery(),
                ),
                ChoicePresentation(
                    "same",
                    "Match recovery-sheet quorum",
                    state.create_signing_key_recovery
                    and state.signing_key_recovery_threshold is None
                    and state.signing_key_recovery_count is None
                    and state.signing_key_replacement_count is None,
                ),
                ChoicePresentation(
                    "custom",
                    "Custom quorum",
                    (
                        state.signing_key_recovery_threshold is not None
                        or state.signing_key_recovery_count is not None
                    ),
                ),
                ChoicePresentation(
                    "replace",
                    "Replace existing key sheets",
                    state.signing_key_replacement_count is not None,
                ),
            ),
            actions=(
                WorkspaceAction("workspace-replace-signing-key-quorum", "Set quorum..."),
                WorkspaceAction("workspace-replace-signing-key-count", "Set count..."),
                WorkspaceAction("workspace-replace-signing-key-payloads", "Key payloads..."),
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
    threshold, count = state.signing_key_recovery_quorum()
    return f"{count} key sheets; any {threshold} can recover the key"


def review_details(
    state: ReplaceRecoveryDocsTaskState,
    plan: TaskExecutionPlan,
) -> tuple[ReviewDetail, ...]:
    source = recovery_source_summary(state)

    recovery = (
        f"{state.recovery_document_count} new sheets ({state.recovery_threshold} needed to restore)"
    )
    if not state.create_passphrase_recovery:
        passphrase = "without passphrase sheets"
    elif state.passphrase_replacement_count is not None:
        passphrase = f"replacing {state.passphrase_replacement_count} passphrase sheets"
    else:
        passphrase = "with passphrase sheets"

    if not state._creates_signing_key_recovery():
        signing = "None"
    elif state.signing_key_replacement_count is not None:
        signing = f"Replace {state.signing_key_replacement_count} sheets"
    else:
        threshold, count = state.signing_key_recovery_quorum()
        signing = f"{count} new sheets ({threshold} required)"
    return (
        ReviewDetail("Source", source, "source"),
        ReviewDetail("Unlock", unlock_input_summary(state), "unlock"),
        ReviewDetail("Recovery sheets", f"{recovery}, {passphrase}", "recovery"),
        ReviewDetail("Signing-key sheets", signing, "signature"),
        ReviewDetail("Layout", layout_summary(state.paper_size, state.design), "layout", "output"),
        ReviewDetail("Destination", destination_summary(plan), "output", "output"),
    )
