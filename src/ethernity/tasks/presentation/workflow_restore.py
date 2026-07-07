from __future__ import annotations

from ethernity.tasks.models import TaskSection
from ethernity.tasks.presentation.common import (
    auth_material_summary,
    section_value,
    source_values,
)
from ethernity.tasks.presentation.models import (
    WorkspaceAction,
    WorkspaceChoice,
    WorkspaceGroup,
    WorkspaceValue,
)
from ethernity.tasks.restore import RestoreTaskState


def restore_groups(
    state: RestoreTaskState,
    sections: dict[str, TaskSection],
) -> tuple[WorkspaceGroup, ...]:
    return (
        WorkspaceGroup(
            key="source",
            title="Backup to restore",
            kind="paths",
            values=source_values(
                scan_paths=tuple(state.source_paths),
                recovery_text_file=state.recovery_text_file,
                payloads_file=state.payloads_file,
            ),
            actions=(
                WorkspaceAction("workspace-restore-source", "Load scanned pages..."),
                WorkspaceAction("workspace-restore-recovery-text", "Paste recovery text..."),
                WorkspaceAction("workspace-restore-payloads", "Load payload files..."),
                WorkspaceAction("workspace-restore-expected-head", "Show fingerprint..."),
            ),
            empty_label=(
                "No backup loaded yet. Load scans, paste recovery text, or choose payload files."
            ),
        ),
        WorkspaceGroup(
            key="unlock",
            title="Unlock backup",
            kind="radio",
            values=(section_value(sections["unlock"]),),
            choices=(
                WorkspaceChoice("passphrase", "Enter passphrase", bool(state.passphrase)),
                WorkspaceChoice(
                    "recovery_documents",
                    "Use recovery sheets",
                    bool(state.recovery_documents),
                ),
                WorkspaceChoice(
                    "recovery_payloads",
                    "Use recovery payload files",
                    bool(state.recovery_payload_files),
                ),
            ),
            actions=(WorkspaceAction("workspace-restore-unlock", "Set unlock method..."),),
        ),
        WorkspaceGroup(
            key="target",
            title="Choose version to restore",
            kind="radio",
            values=(section_value(sections["target"]),),
            choices=(
                WorkspaceChoice("latest", "Newest loaded version", state.target == "latest"),
                WorkspaceChoice("original", "Initial backup only", state.target == "original"),
                WorkspaceChoice(
                    "specific_update",
                    "Specific version/update",
                    state.target == "specific_update",
                ),
            ),
            actions=(
                WorkspaceAction("workspace-restore-target", "Set version/update..."),
                WorkspaceAction("workspace-restore-target-fingerprint", "Show fingerprint..."),
            ),
        ),
        WorkspaceGroup(
            key="authentication",
            title="Signature check",
            kind="policy",
            values=(
                WorkspaceValue(
                    "allow-unsigned",
                    "Signature check",
                    "Allow unsigned legacy recovery"
                    if state.allow_unsigned
                    else "Require trusted signature",
                ),
                WorkspaceValue(
                    "auth-material",
                    "Trust source",
                    auth_material_summary(state.auth_text_file, state.auth_payloads_file),
                ),
            ),
        ),
        WorkspaceGroup(
            key="output",
            title="Choose restore destination",
            kind="output",
            values=(section_value(sections["output"]),),
            actions=(WorkspaceAction("workspace-restore-output", "Choose restore folder..."),),
        ),
    )
