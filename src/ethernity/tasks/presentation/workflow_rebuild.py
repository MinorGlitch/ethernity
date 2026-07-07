from __future__ import annotations

from pathlib import Path

from ethernity.tasks.models import TaskSection
from ethernity.tasks.presentation.common import (
    auth_material_summary,
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
from ethernity.tasks.rebuild import RebuildTaskState


def rebuild_groups(
    state: RebuildTaskState,
    sections: dict[str, TaskSection],
) -> tuple[WorkspaceGroup, ...]:
    source_paths: tuple[Path, ...] = tuple(state.source_paths)
    if state.backup_folder is not None:
        source_paths = (state.backup_folder,)
    return (
        WorkspaceGroup(
            key="source",
            title="Existing backup",
            kind="paths",
            values=path_values("source", source_paths),
            actions=(
                WorkspaceAction("workspace-rebuild-source", "Choose backup folder..."),
                WorkspaceAction(
                    "workspace-rebuild-freshness",
                    "Use this backup",
                    enabled=bool(state.source_paths),
                ),
                WorkspaceAction(
                    "workspace-rebuild-fingerprint",
                    "Show fingerprint...",
                    enabled=bool(state.source_paths),
                ),
            ),
            empty_label="No backup loaded yet. Choose a backup folder or load scanned pages.",
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
            actions=(WorkspaceAction("workspace-rebuild-unlock", "Set unlock method..."),),
        ),
        WorkspaceGroup(
            key="output",
            title="Save rebuilt backup documents to",
            kind="layout",
            values=(
                section_value(sections["output"]),
                WorkspaceValue("freshness", "Freshness", sections["freshness"].summary),
                WorkspaceValue(
                    "auth-material",
                    "Trust source",
                    auth_material_summary(state.auth_text_file, state.auth_payloads_file),
                ),
                WorkspaceValue(
                    "qr-chunk-size",
                    "QR density",
                    qr_chunk_size_summary(state.qr_chunk_size),
                ),
                WorkspaceValue("paper", "Paper size", state.paper_size),
                WorkspaceValue("design", "Print design", state.design),
            ),
            actions=(
                WorkspaceAction("workspace-rebuild-output", "Choose output folder..."),
                WorkspaceAction("workspace-rebuild-qr-chunk-size", "Set QR density..."),
            ),
        ),
    )
