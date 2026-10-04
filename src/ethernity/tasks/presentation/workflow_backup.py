from __future__ import annotations

from ethernity.render.recovery_kit_index import supports_recovery_kit_index_style
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.backup_inputs import has_selected_inputs
from ethernity.tasks.file_summary import display_path, format_count
from ethernity.tasks.models import TaskSection
from ethernity.tasks.presentation.models import (
    ChoicePresentation,
    WorkspaceAction,
    WorkspaceGroup,
    WorkspaceValue,
)
from ethernity.tasks.presentation.presentation_values import (
    path_values,
    qr_chunk_size_control_value,
    qr_chunk_size_summary,
    section_value,
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
                    visible=has_selected_inputs(state.input_paths, state.input_dirs),
                ),
            ),
            empty_label="No files selected.",
            status=sections["files"].status,
            status_summary=_backup_files_summary(state),
        ),
        WorkspaceGroup(
            key="print",
            title="Print setup",
            kind="layout",
            values=(
                WorkspaceValue("paper", "Paper size", state.paper_size),
                WorkspaceValue("design", "Print design", state.design),
            ),
            status=sections["print"].status,
            status_summary=sections["print"].summary,
        ),
        WorkspaceGroup(
            key="documents",
            title="Documents to print",
            kind="layout",
            values=(
                WorkspaceValue("inventory", "Output", _backup_inventory(state)),
                WorkspaceValue("estimate-error", "Print estimate", state.estimate_error() or ""),
            ),
        ),
        WorkspaceGroup(
            key="recovery",
            title="Recovery method",
            kind="radio",
            values=(section_value(sections["recovery"]),),
            choices=(
                ChoicePresentation(
                    "recommended_shards",
                    "3 sheets, any 2 unlock (recommended)",
                    state.recovery_method == "recommended_shards",
                ),
                ChoicePresentation(
                    "single_phrase",
                    "Single recovery phrase",
                    state.recovery_method == "single_phrase",
                ),
                ChoicePresentation(
                    "custom_shards",
                    f"Custom: {state.shard_count} sheets; any {state.shard_threshold} required",
                    state.recovery_method == "custom_shards",
                ),
            ),
            actions=(
                WorkspaceAction(
                    "workspace-backup-recovery-quorum",
                    "Change quorum...",
                    visible=state.recovery_method == "custom_shards",
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
                    control_value=str(state.output_dir) if state.output_dir is not None else "",
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


def _backup_files_summary(state: BackupTaskState) -> str:
    estimate = state.current_estimate()
    if estimate is not None:
        return (
            f"{format_count(estimate.file_count, 'file')}, {_compact_bytes(estimate.input_bytes)}"
        )
    count = len(state.input_paths) + len(state.input_dirs)
    if count == 0:
        return "Choose files to begin"
    noun = "selected path" if state.input_dirs else "selected file"
    if state.estimate_error() is not None:
        return f"{format_count(count, noun)}; size unavailable"
    return f"{format_count(count, noun)}; calculating size..."


def _backup_inventory(state: BackupTaskState) -> str:
    estimate = state.current_estimate()
    backup_pages = (
        f"About {format_count(estimate.backup_pages, 'backup page')}"
        if estimate is not None
        else "Backup pages"
    )
    recovery = (
        "1 recovery phrase"
        if state.recovery_method == "single_phrase"
        else format_count(state.shard_count, "recovery sheet")
    )
    extras = ["guide"]
    if supports_recovery_kit_index_style(state.design):
        extras.append("inventory")
    if state.signing_key_mode == "sharded" and state.recovery_method != "single_phrase":
        count = state.signing_key_shard_count or state.shard_count
        extras.append(format_count(count, "key sheet"))
    return f"{backup_pages} + {recovery}\nAlso: {', '.join(extras)}"


def _compact_bytes(size: int) -> str:
    if size < 1024:
        return format_count(size, "byte")
    value = float(size)
    for unit in ("KiB", "MiB", "GiB"):
        value /= 1024
        if value < 1024:
            return f"{value:.1f} {unit}"
    return f"{value:.1f} GiB"


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
