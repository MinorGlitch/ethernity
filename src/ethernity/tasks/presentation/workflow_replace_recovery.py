from __future__ import annotations

from ethernity.tasks.models import TaskSection
from ethernity.tasks.presentation.common import section_value, source_values
from ethernity.tasks.presentation.models import (
    WorkspaceAction,
    WorkspaceChoice,
    WorkspaceGroup,
    WorkspaceValue,
)
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState


def replace_recovery_groups(
    state: ReplaceRecoveryDocsTaskState,
    sections: dict[str, TaskSection],
) -> tuple[WorkspaceGroup, ...]:
    source_status = sections["source"]
    if source_status.status == "ready" and sections["freshness"].status != "ready":
        source_status = sections["freshness"]
    return (
        WorkspaceGroup(
            key="source",
            title="Existing backup",
            kind="paths",
            values=source_values(
                scan_paths=tuple(state.source_paths),
                recovery_text_file=state.recovery_text_file,
                payloads_file=state.payloads_file,
            ),
            actions=(
                WorkspaceAction("workspace-replace-source", "Load scanned pages..."),
                WorkspaceAction("workspace-replace-recovery-text", "Paste recovery text..."),
                WorkspaceAction("workspace-replace-payloads", "Load payload files..."),
                WorkspaceAction(
                    "workspace-replace-freshness",
                    "Use this backup",
                    enabled=bool(state.source_paths),
                ),
                WorkspaceAction(
                    "workspace-replace-fingerprint",
                    "Show fingerprint...",
                    enabled=bool(state.source_paths),
                ),
            ),
            empty_label=(
                "No backup loaded yet. Load scans, paste recovery text, or choose payload files."
            ),
            status=source_status.status,
            status_summary=source_status.summary,
        ),
        WorkspaceGroup(
            key="unlock",
            title="Unlock existing backup",
            kind="radio",
            values=(section_value(sections["unlock"]),),
            choices=(
                WorkspaceChoice("passphrase", "Enter passphrase", bool(state.passphrase)),
                WorkspaceChoice(
                    "recovery_documents",
                    "Use current recovery sheets",
                    bool(state.recovery_documents),
                ),
                WorkspaceChoice(
                    "recovery_payloads",
                    "Use recovery payload files",
                    bool(state.recovery_payload_files),
                ),
            ),
            actions=(WorkspaceAction("workspace-replace-unlock", "Set unlock method..."),),
            status=sections["unlock"].status,
            status_summary=sections["unlock"].summary,
        ),
        WorkspaceGroup(
            key="recovery",
            title="New recovery method",
            kind="radio",
            values=(
                section_value(sections["recovery"]),
                WorkspaceValue(
                    "passphrase-recovery",
                    "Passphrase recovery",
                    state.passphrase_recovery_summary(),
                ),
            ),
            choices=(
                WorkspaceChoice(
                    "recommended",
                    "3 new recovery sheets; any 2 can restore",
                    state.recovery_threshold == 2 and state.recovery_document_count == 3,
                ),
                WorkspaceChoice(
                    "custom",
                    (
                        f"Custom recovery sheets: any {state.recovery_threshold} "
                        f"of {state.recovery_document_count}"
                    ),
                    state.recovery_threshold != 2 or state.recovery_document_count != 3,
                ),
            ),
            actions=(
                WorkspaceAction("workspace-replace-recovery", "Change recovery method..."),
                WorkspaceAction("workspace-replace-passphrase-count", "Set passphrase sheets..."),
            ),
            status=sections["recovery"].status,
            status_summary=sections["recovery"].summary,
        ),
        WorkspaceGroup(
            key="output",
            title="Save replacement sheets to",
            kind="layout",
            values=(
                WorkspaceValue(
                    "output",
                    "Save documents to",
                    section_value(sections["output"]).value,
                ),
                WorkspaceValue(
                    "safety",
                    "Safety",
                    "Existing backup files are not deleted or modified.",
                ),
            ),
            actions=(WorkspaceAction("workspace-replace-output", "Choose output folder..."),),
            status=sections["output"].status,
            status_summary=sections["output"].summary,
        ),
        WorkspaceGroup(
            key="layout",
            title="Print options",
            kind="layout",
            values=(
                WorkspaceValue("paper", "Paper size", state.paper_size),
                WorkspaceValue("design", "Print design", state.design),
            ),
            status=sections["layout"].status,
            status_summary=sections["layout"].summary,
        ),
        WorkspaceGroup(
            key="signing-key-recovery",
            title="Signature",
            kind="radio",
            values=(
                WorkspaceValue(
                    "signing-key",
                    "Signing key recovery",
                    replace_signing_key_recovery_summary(state),
                ),
                WorkspaceValue(
                    "signing-key-payloads",
                    "Signing key payloads",
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
                    "Use same quorum as recovery sheets",
                    state.mint_signing_key_recovery
                    and state.signing_key_recovery_threshold is None
                    and state.signing_key_recovery_count is None
                    and state.signing_key_replacement_count is None,
                ),
                WorkspaceChoice(
                    "custom",
                    "Custom signing key quorum",
                    state.signing_key_recovery_threshold is not None
                    or state.signing_key_recovery_count is not None,
                ),
                WorkspaceChoice(
                    "replace",
                    "Replace existing signing-key recovery sheets",
                    state.signing_key_replacement_count is not None,
                ),
            ),
            actions=(
                WorkspaceAction("workspace-replace-signing-key-count", "Set signing sheets..."),
                WorkspaceAction("workspace-replace-signing-key-payloads", "Load key payloads..."),
            ),
            status=sections["signature"].status,
            status_summary=sections["signature"].summary,
        ),
    )


def replace_signing_key_recovery_summary(state: ReplaceRecoveryDocsTaskState) -> str:
    if not state._creates_signing_key_recovery():
        return "Off - not signed"
    if state.signing_key_replacement_count is not None:
        return f"{state.signing_key_replacement_count} replacement sheet(s)"
    threshold = state.signing_key_recovery_threshold or state.recovery_threshold
    count = state.signing_key_recovery_count or state.recovery_document_count
    return f"Any {threshold} of {count} signing-key recovery sheets"
