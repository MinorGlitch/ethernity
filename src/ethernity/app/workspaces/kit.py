from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Button, Select, Static

from ethernity.app.widgets.form import FormRow, FormScroll, FormSection
from ethernity.app.widgets.static_text import PathLabel, update_static_text
from ethernity.app.widgets.workflow.controls import InlineNotice
from ethernity.app.workspaces.workspace_controls import (
    DESIGN_OPTIONS,
    KIT_VARIANTS,
    PAPER_OPTIONS,
    BaseWorkspace,
    control_value,
    field_row,
    first_value,
    group,
    select_row,
    set_select,
    value,
)
from ethernity.page_sizes import paper_size_display_name
from ethernity.render.designs import (
    load_design_definition_by_name,
    supported_paper_size_names,
)
from ethernity.tasks.page_layout import KIT_RENDER_DOC_TYPES
from ethernity.tasks.presentation.models import (
    InlineNoticePresentation,
    TaskPresentation,
    WorkspaceAction,
)


class KitWorkspace(BaseWorkspace):
    task_key = "kit"

    def compose(self) -> ComposeResult:
        with FormScroll(classes="task-workspace"):
            with FormSection("PDF file"):
                yield FormRow(
                    "Save as",
                    PathLabel("", id="kit-output-value", classes="field-text form-path-value"),
                    Button("Change...", id="workspace-kit-output", tooltip="Choose PDF..."),
                )
                yield InlineNotice(id="kit-output-notice")
            with FormSection("Print setup"):
                yield select_row("Kit type", "workspace-kit-variant-select", KIT_VARIANTS)
                yield select_row("Paper size", "workspace-kit-paper", PAPER_OPTIONS)
                yield select_row("Print design", "workspace-kit-design", DESIGN_OPTIONS)
            with FormSection("QR codes"):
                yield field_row(
                    "Bytes per code",
                    "kit-chunk-size-value",
                    WorkspaceAction("workspace-kit-chunk-size", "Set QR sizing..."),
                )
                yield InlineNotice(id="kit-qr-warning")

    def update_presentation(self, presentation: TaskPresentation) -> None:
        super().update_presentation(presentation)
        variant = group(presentation, "variant")
        set_select(
            self.query_one("#workspace-kit-variant-select", Select),
            value(variant, "variant"),
        )
        layout = group(presentation, "layout")
        paper_select = self.query_one("#workspace-kit-paper", Select)
        design_name = value(layout, "design")
        definition = load_design_definition_by_name(design_name)
        supported_names = supported_paper_size_names(
            design_name,
            doc_types=definition.documents & KIT_RENDER_DOC_TYPES,
        )
        with paper_select.prevent(Select.Changed):
            paper_select.set_options(
                [(paper_size_display_name(name), name) for name in supported_names]
            )
        set_select(paper_select, value(layout, "paper"))
        set_select(self.query_one("#workspace-kit-design", Select), value(layout, "design"))

        output = group(presentation, "output")
        self.query_one("#kit-output-value", PathLabel).set_path(
            control_value(output, "output"), first_value(output)
        )
        notice = None
        if output.status == "warning":
            notice = InlineNoticePresentation(
                "This PDF exists. Creating the kit will replace it.",
                tone="warning",
            )
        elif output.status == "blocked":
            notice = InlineNoticePresentation(
                "Choose a valid PDF output path.",
                tone="error",
            )
        self.query_one("#kit-output-notice", InlineNotice).sync_presentation(notice)

        qr = group(presentation, "qr")
        qr_summary = value(qr, "chunk-size")
        qr_warning = None
        if qr.status == "warning":
            qr_warning = InlineNoticePresentation(
                "Custom QR sizing may make codes harder to scan.",
                tone="warning",
            )
        self.query_one("#kit-qr-warning", InlineNotice).sync_presentation(qr_warning)
        update_static_text(
            self.query_one("#kit-chunk-size-value", Static),
            qr_summary,
        )
