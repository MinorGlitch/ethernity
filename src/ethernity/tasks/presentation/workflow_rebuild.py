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
            status=sections["source"].status,
            status_summary=sections["source"].summary,
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
            status=sections["unlock"].status,
            status_summary=sections["unlock"].summary,
        ),
        WorkspaceGroup(
            key="options",
            title="Rebuild options",
            kind="layout",
            values=(
                WorkspaceValue("freshness", "Version included", sections["freshness"].summary),
                WorkspaceValue(
                    "safety",
                    "Safety",
                    "Existing backup files are not deleted or modified.",
                ),
            ),
            status=sections["freshness"].status,
            status_summary=sections["freshness"].summary,
        ),
        WorkspaceGroup(
            key="output",
            title="Save rebuilt backup documents to",
            kind="layout",
            values=(section_value(sections["output"]),),
            actions=(WorkspaceAction("workspace-rebuild-output", "Choose output folder..."),),
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
            ),
            actions=(WorkspaceAction("workspace-rebuild-qr-chunk-size", "Set QR density..."),),
            status=sections["advanced"].status,
            status_summary=sections["advanced"].summary,
        ),
    )
