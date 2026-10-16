from __future__ import annotations

from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.backup_facts import BackupFacts
from ethernity.tasks.backup_inputs import has_selected_inputs
from ethernity.tasks.file_summary import format_count, selected_items_summary
from ethernity.tasks.models import TaskExecutionPlan, TaskSection
from ethernity.tasks.presentation.models import (
    ChoicePresentation,
    ReviewDetail,
    WorkspaceAction,
    WorkspaceGroup,
    WorkspaceValue,
)
from ethernity.tasks.presentation.presentation_values import (
    advanced_fields_group,
    base_directory_value,
    path_values,
    print_layout_group,
    qr_density_value,
    section_value,
)
from ethernity.tasks.presentation.review_values import (
    destination_summary,
    layout_summary,
)


def backup_groups(
    state: BackupTaskState,
    sections: dict[str, TaskSection],
) -> tuple[WorkspaceGroup, ...]:
    facts = state.facts()
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
            status_summary=_backup_files_summary(facts),
        ),
        print_layout_group(state.paper_size, state.design, sections["print"]),
        WorkspaceGroup(
            key="documents",
            title="Documents to print",
            kind="layout",
            values=(
                WorkspaceValue("inventory", "Output", facts.compact_document_summary),
                WorkspaceValue("estimate-error", "Print estimate", facts.estimate_error or ""),
            ),
        ),
        WorkspaceGroup(
            key="recovery",
            title="Recovery method",
            kind="radio",
            values=(
                section_value(sections["recovery"]),
                WorkspaceValue("storage-note", "Storage", facts.storage_note),
            ),
            choices=tuple(
                ChoicePresentation(option.key, option.label, option.selected)
                for option in facts.recovery_options
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
        advanced_fields_group(
            sections["advanced"],
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
                base_directory_value(state.base_dir),
                qr_density_value(state.qr_chunk_size),
                WorkspaceValue(
                    "signing-key",
                    "Signing-key recovery",
                    facts.signing_summary,
                    control_value=state.signing_key_mode,
                ),
            ),
            actions=(
                WorkspaceAction("workspace-backup-passphrase", "Set passphrase..."),
                WorkspaceAction("workspace-backup-base-dir", "Choose base folder..."),
                WorkspaceAction("workspace-backup-qr-chunk-size", "Set QR density..."),
                WorkspaceAction("workspace-backup-signing-key-shards", "Set quorum..."),
            ),
        ),
    )


def _backup_files_summary(facts: BackupFacts) -> str:
    estimate = facts.estimate
    if estimate is not None:
        return (
            f"{format_count(estimate.file_count, 'file')}, {_compact_bytes(estimate.input_bytes)}"
        )
    count = facts.selected_files + facts.selected_folders
    if count == 0:
        return "Choose files to begin"
    noun = "selected path" if facts.selected_folders else "selected file"
    if facts.estimate_error is not None:
        return f"{format_count(count, noun)}; size unavailable"
    return f"{format_count(count, noun)}; calculating size..."


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


def review_details(
    state: BackupTaskState,
    plan: TaskExecutionPlan,
) -> tuple[ReviewDetail, ...]:
    facts = state.facts()
    file_count = facts.selected_files
    folder_count = facts.selected_folders
    selected = selected_items_summary(file_count, folder_count)
    recovery = (
        "One recovery phrase"
        if facts.recovery is None
        else f"{facts.recovery.total} sheets, {facts.recovery.required} needed to restore"
    )
    signing = (
        "Encrypted in the backup documents"
        if facts.signing_key_mode == "embedded"
        else facts.signing_summary
    )
    estimate = facts.estimate
    if estimate is not None and folder_count:
        selected = f"{format_count(estimate.file_count, 'file')} from {selected}"
    print_estimate = (
        (
            ReviewDetail(
                "Backup pages",
                f"About {format_count(estimate.backup_pages, 'page')} in the main PDF",
                group="output",
            ),
        )
        if estimate is not None
        else ()
    )
    return (
        ReviewDetail("Files", selected, "files"),
        ReviewDetail("Recovery", recovery, "recovery"),
        ReviewDetail("Signing key", signing, "signature"),
        ReviewDetail("Documents", facts.document_summary, group="output"),
        *print_estimate,
        ReviewDetail("Layout", layout_summary(state.paper_size, state.design), "layout", "output"),
        ReviewDetail(
            "Destination",
            destination_summary(plan),
            "output",
            "output",
        ),
    )
