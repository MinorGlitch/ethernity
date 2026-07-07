from __future__ import annotations

from ethernity.tasks.kit import PrintKitTaskState
from ethernity.tasks.models import TaskSection
from ethernity.tasks.presentation.common import qr_chunk_size_summary, section_value
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
            title="Save PDF as",
            kind="output",
            values=(section_value(sections["output"]),),
            actions=(WorkspaceAction("workspace-kit-output", "Choose PDF path..."),),
            status=sections["output"].status,
            status_summary=sections["output"].summary,
        ),
        WorkspaceGroup(
            key="layout",
            title="Print layout",
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
                WorkspaceValue("chunk-size", "QR sizing", qr_chunk_size_summary(state.chunk_size)),
            ),
            actions=(WorkspaceAction("workspace-kit-chunk-size", "Set QR sizing..."),),
            status_summary=qr_chunk_size_summary(state.chunk_size),
        ),
    )
