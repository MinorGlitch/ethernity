from __future__ import annotations

from pathlib import Path

from ethernity.tasks.file_summary import display_path
from ethernity.tasks.kit import PrintKitTaskState
from ethernity.tasks.models import TaskSection
from ethernity.tasks.presentation.common import (
    qr_chunk_size_control_value,
)
from ethernity.tasks.presentation.models import WorkspaceAction, WorkspaceGroup, WorkspaceValue


def kit_groups(
    state: PrintKitTaskState,
    sections: dict[str, TaskSection],
) -> tuple[WorkspaceGroup, ...]:
    return (
        WorkspaceGroup(
            key="variant",
            title="Kit type",
            kind="layout",
            values=(WorkspaceValue("variant", "Kit type", state.variant),),
            status=sections["variant"].status,
            status_summary=sections["variant"].summary,
        ),
        WorkspaceGroup(
            key="output",
            title="PDF file",
            kind="output",
            values=(WorkspaceValue("output", "Save as", _kit_output_display(state)),),
            actions=(WorkspaceAction("workspace-kit-output", "Choose PDF file..."),),
            status=sections["output"].status,
            status_summary=_kit_output_display(state),
        ),
        WorkspaceGroup(
            key="layout",
            title="Print setup",
            kind="layout",
            values=(
                WorkspaceValue("paper", "Paper size", state.paper_size),
                WorkspaceValue("design", "Print design", state.design),
            ),
            status=sections["layout"].status,
            status_summary=sections["layout"].summary,
        ),
        WorkspaceGroup(
            key="qr",
            title="QR sizing",
            kind="fields",
            values=(
                WorkspaceValue(
                    "chunk-size",
                    "Bytes per code",
                    _kit_qr_summary(state.chunk_size),
                    control_value=qr_chunk_size_control_value(state.chunk_size),
                ),
            ),
            actions=(WorkspaceAction("workspace-kit-chunk-size", "Set QR sizing..."),),
            status=sections["qr"].status,
            status_summary=sections["qr"].summary,
        ),
    )


def _kit_output_display(state: PrintKitTaskState) -> str:
    if state.output_path.is_absolute():
        summary = display_path(state.output_path)
    elif state.output_path.parent == Path("."):
        summary = f"{state.output_path} (current folder)"
    else:
        summary = f"{display_path(state.output_path)} (relative)"
    return summary


def _kit_qr_summary(chunk_size: int | None) -> str:
    if chunk_size is None:
        return "Automatic (recommended)"
    return f"{chunk_size} bytes per code"
