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
            key="print",
            title="Print layout",
            kind="layout",
            values=(
                WorkspaceValue("variant", "Kit type", state.variant),
                WorkspaceValue("paper", "Paper size", state.paper_size),
                WorkspaceValue("design", "Print design", state.design),
                WorkspaceValue("chunk-size", "QR sizing", qr_chunk_size_summary(state.chunk_size)),
            ),
            actions=(WorkspaceAction("workspace-kit-chunk-size", "Set QR sizing..."),),
        ),
        WorkspaceGroup(
            key="output",
            title="Save PDF as",
            kind="output",
            values=(section_value(sections["output"]),),
            actions=(WorkspaceAction("workspace-kit-output", "Choose PDF path..."),),
        ),
    )
