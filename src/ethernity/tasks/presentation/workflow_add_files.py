from __future__ import annotations

from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.models import TaskSection
from ethernity.tasks.presentation.common import (
    path_values,
    qr_chunk_size_summary,
    section_value,
)
from ethernity.tasks.presentation.models import (
    WorkspaceAction,
    WorkspaceChoice,
    WorkspaceGroup,
    WorkspaceValue,
)


def add_files_groups(
    state: AddFilesTaskState,
    sections: dict[str, TaskSection],
) -> tuple[WorkspaceGroup, ...]:
    return (
        WorkspaceGroup(
            key="backup",
            title="Existing backup",
            kind="output",
            values=(section_value(sections["backup"]), section_value(sections["source"])),
            actions=(
                WorkspaceAction("workspace-add-files-backup", "Choose backup folder..."),
                WorkspaceAction("workspace-add-files-source", "Load scanned pages..."),
                WorkspaceAction(
                    "workspace-add-files-freshness",
                    "Use this backup",
                    enabled=bool(state.source_paths),
                ),
                WorkspaceAction(
                    "workspace-add-files-fingerprint",
                    "Show fingerprint...",
                    enabled=bool(state.source_paths),
                ),
            ),
        ),
        WorkspaceGroup(
            key="files",
            title="Files to add",
            kind="paths",
            values=path_values("file", (*state.input_paths, *state.input_dirs)),
            actions=(WorkspaceAction("workspace-add-files-files", "Choose files..."),),
            empty_label="No files selected yet. Choose at least one file or folder.",
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
            actions=(WorkspaceAction("workspace-add-files-unlock", "Set unlock method..."),),
        ),
        WorkspaceGroup(
            key="options",
            title="Print options",
            kind="layout",
            values=(
                WorkspaceValue("paper", "Paper size", state.paper_size),
                WorkspaceValue("design", "Print design", state.design),
            ),
        ),
        WorkspaceGroup(
            key="advanced",
            title="Advanced",
            kind="fields",
            values=(
                WorkspaceValue(
                    "base-dir",
                    "Base folder",
                    str(state.base_dir)
                    if state.base_dir is not None
                    else "Automatic, based on selected files",
                ),
                WorkspaceValue(
                    "qr-chunk-size",
                    "QR density",
                    qr_chunk_size_summary(state.qr_chunk_size),
                ),
                WorkspaceValue(
                    "unlock-policy",
                    "Unlock policy",
                    add_files_unlock_policy_summary(state),
                ),
                WorkspaceValue(
                    "recovery-docs",
                    "Recovery sheets",
                    add_files_recovery_summary(state),
                ),
                WorkspaceValue("signing-key", "Signing key", add_files_signing_key_summary(state)),
            ),
            actions=(
                WorkspaceAction("workspace-add-files-base-dir", "Choose base folder..."),
                WorkspaceAction("workspace-add-files-qr-chunk-size", "Set QR density..."),
            ),
        ),
    )


def add_files_unlock_policy_summary(state: AddFilesTaskState) -> str:
    if state.unlock_policy == "reuse-root":
        return "Reuse root recovery"
    return "Self-contained update"


def add_files_recovery_summary(state: AddFilesTaskState) -> str:
    if state.recovery_document_count == 0:
        return "No new recovery sheets"
    if state.recovery_document_threshold is not None and state.recovery_document_count is not None:
        return (
            f"{state.recovery_document_count} recovery sheets; "
            f"any {state.recovery_document_threshold} required"
        )
    return "Using saved recovery-sheet defaults"


def add_files_signing_key_summary(state: AddFilesTaskState) -> str:
    if state.signing_key_mode is None:
        return "Using saved signing-key default"
    if state.signing_key_mode == "not-stored":
        return "Not stored"
    if (
        state.signing_key_recovery_threshold is not None
        and state.signing_key_recovery_count is not None
    ):
        return (
            f"Sharded, any {state.signing_key_recovery_threshold} "
            f"of {state.signing_key_recovery_count}"
        )
        return "Sharded signing key"
