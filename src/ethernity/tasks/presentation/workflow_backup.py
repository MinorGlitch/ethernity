from __future__ import annotations

from ethernity.tasks.backup import BackupTaskState
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


def backup_groups(
    state: BackupTaskState,
    sections: dict[str, TaskSection],
) -> tuple[WorkspaceGroup, ...]:
    return (
        WorkspaceGroup(
            key="files",
            title="Files to back up",
            kind="paths",
            values=path_values("file", (*state.input_paths, *state.input_dirs)),
            actions=(WorkspaceAction("workspace-backup-files", "Choose files..."),),
            empty_label="No files selected yet. Choose at least one file or folder.",
            status=sections["files"].status,
            status_summary=sections["files"].summary,
        ),
        WorkspaceGroup(
            key="recovery",
            title="Recovery",
            kind="radio",
            values=(section_value(sections["recovery"]),),
            choices=(
                WorkspaceChoice(
                    "recommended_shards",
                    "Recommended: 3 recovery sheets; any 2 can restore",
                    state.recovery_method == "recommended_shards",
                ),
                WorkspaceChoice(
                    "single_phrase",
                    "Single recovery phrase",
                    state.recovery_method == "single_phrase",
                ),
                WorkspaceChoice(
                    "custom_shards",
                    f"Custom recovery sheets: any {state.shard_threshold} of {state.shard_count}",
                    state.recovery_method == "custom_shards",
                ),
            ),
            status=sections["recovery"].status,
            status_summary=sections["recovery"].summary,
        ),
        WorkspaceGroup(
            key="destination",
            title="Save backup documents to",
            kind="layout",
            values=(section_value(sections["output"]),),
            actions=(WorkspaceAction("workspace-backup-output", "Choose output folder..."),),
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
            key="advanced",
            title="Advanced",
            kind="fields",
            values=(
                WorkspaceValue("passphrase", "Passphrase", backup_passphrase_summary(state)),
                WorkspaceValue(
                    "passphrase-words",
                    "Generated words",
                    str(state.passphrase_words)
                    if state.passphrase_words is not None
                    else "Default: saved setting",
                ),
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
                WorkspaceValue("signing-key", "Signing key", backup_signing_key_summary(state)),
            ),
            actions=(
                WorkspaceAction("workspace-backup-passphrase", "Set passphrase..."),
                WorkspaceAction("workspace-backup-base-dir", "Choose base folder..."),
                WorkspaceAction("workspace-backup-qr-chunk-size", "Set QR density..."),
                WorkspaceAction("workspace-backup-signing-key-shards", "Set key sheets..."),
            ),
            status=sections["advanced"].status,
            status_summary=sections["advanced"].summary,
        ),
    )


def backup_passphrase_summary(state: BackupTaskState) -> str:
    if state.passphrase is not None:
        return "Custom"
    if state.passphrase_words is not None:
        return f"{state.passphrase_words} generated words"
    return "Generated automatically"


def backup_signing_key_summary(state: BackupTaskState) -> str:
    if state.signing_key_mode != "sharded":
        return "Embedded signing key"
    threshold = state.signing_key_shard_threshold or state.shard_threshold
    count = state.signing_key_shard_count or state.shard_count
    return f"Sharded, any {threshold} of {count} key sheets"
