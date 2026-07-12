from __future__ import annotations

from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.file_summary import display_path
from ethernity.tasks.models import TaskSection
from ethernity.tasks.presentation.common import (
    path_values,
    qr_chunk_size_control_value,
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
            actions=(
                WorkspaceAction("workspace-backup-files", "Choose files..."),
                WorkspaceAction(
                    "workspace-backup-clear-files",
                    "Clear files",
                    visible=bool(state.input_paths or state.input_dirs),
                ),
            ),
            empty_label="No files selected.",
            status=sections["files"].status,
            status_summary=sections["files"].summary,
        ),
        WorkspaceGroup(
            key="recovery",
            title="Recovery method",
            kind="radio",
            values=(section_value(sections["recovery"]),),
            choices=(
                WorkspaceChoice(
                    "recommended_shards",
                    "3 recovery sheets; any 2 can restore (recommended)",
                    state.recovery_method == "recommended_shards",
                ),
                WorkspaceChoice(
                    "single_phrase",
                    "Single recovery phrase",
                    state.recovery_method == "single_phrase",
                ),
                WorkspaceChoice(
                    "custom_shards",
                    f"Custom: {state.shard_count} sheets; any {state.shard_threshold} required",
                    state.recovery_method == "custom_shards",
                ),
            ),
            status=sections["recovery"].status,
            status_summary=sections["recovery"].summary,
        ),
        WorkspaceGroup(
            key="destination",
            title="Destination",
            kind="layout",
            values=(
                WorkspaceValue(
                    "output",
                    "Folder",
                    sections["output"].summary,
                    status=sections["output"].status,
                ),
            ),
            actions=(WorkspaceAction("workspace-backup-output", "Choose folder..."),),
            status=sections["output"].status,
            status_summary=sections["output"].summary,
        ),
        WorkspaceGroup(
            key="advanced",
            title="Advanced",
            kind="fields",
            values=(
                WorkspaceValue(
                    "passphrase",
                    "Passphrase",
                    backup_passphrase_summary(state),
                    control_value="custom" if state.passphrase is not None else "generated",
                ),
                WorkspaceValue(
                    "passphrase-words",
                    "Generated passphrase",
                    str(state.passphrase_words)
                    if state.passphrase_words is not None
                    else "From settings",
                    control_value=(
                        str(state.passphrase_words)
                        if state.passphrase_words is not None
                        else "default"
                    ),
                ),
                WorkspaceValue(
                    "base-dir",
                    "Base folder",
                    display_path(state.base_dir)
                    if state.base_dir is not None
                    else "Based on selected files",
                    control_value="custom" if state.base_dir is not None else "automatic",
                ),
                WorkspaceValue(
                    "qr-chunk-size",
                    "QR density",
                    qr_chunk_size_summary(state.qr_chunk_size),
                    control_value=qr_chunk_size_control_value(state.qr_chunk_size),
                ),
                WorkspaceValue(
                    "signing-key",
                    "Signing-key recovery",
                    backup_signing_key_summary(state),
                    control_value=state.signing_key_mode,
                ),
            ),
            actions=(
                WorkspaceAction("workspace-backup-passphrase", "Set passphrase..."),
                WorkspaceAction("workspace-backup-base-dir", "Choose base folder..."),
                WorkspaceAction("workspace-backup-qr-chunk-size", "Set QR density..."),
                WorkspaceAction("workspace-backup-signing-key-shards", "Set quorum..."),
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
    return "Generated"


def backup_signing_key_summary(state: BackupTaskState) -> str:
    if state.signing_key_mode != "sharded":
        return "Embedded in backup"
    threshold = state.signing_key_shard_threshold or state.shard_threshold
    count = state.signing_key_shard_count or state.shard_count
    return f"{count} key sheets; any {threshold} can recover the key"
