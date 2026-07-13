from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Collapsible, Select, Static

from ethernity.app.widgets.collapsible import panel_title
from ethernity.app.widgets.static_text import update_static_text
from ethernity.app.widgets.workflow.controls import InlineNotice
from ethernity.app.workspaces.common import (
    DESIGN_OPTIONS,
    KIT_VARIANTS,
    PAPER_OPTIONS,
    BaseWorkspace,
    advanced_panel,
    field_row,
    first_value,
    group,
    group_label,
    section,
    select_row,
    set_select,
    value,
)
from ethernity.page_sizes import paper_size_display_name
from ethernity.render.designs import (
    load_design_manifest_by_name,
    supported_paper_size_names,
)
from ethernity.tasks.page_layout import KIT_RENDER_DOC_TYPES
from ethernity.tasks.presentation.models import (
    InlineNoticePresentation,
    TaskPresentation,
    WorkspaceAction,
)

KIT_ADVANCED_PANEL_ID = "kit-advanced-panel"


class KitWorkspace(BaseWorkspace):
    task_key = "kit"
    advanced_panel_id = KIT_ADVANCED_PANEL_ID

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="task-workspace compact-form-workspace"):
            with section():
                yield group_label("PDF file")
                yield field_row(
                    "Save as",
                    "kit-output-value",
                    WorkspaceAction("workspace-kit-output", "Choose PDF file..."),
                )
                yield InlineNotice(id="kit-output-notice")
            with section():
                yield InlineNotice(id="kit-qr-warning")
                with advanced_panel(KIT_ADVANCED_PANEL_ID, "QR sizing - Automatic"):
                    yield field_row(
                        "Bytes per code",
                        "kit-chunk-size-value",
                        WorkspaceAction("workspace-kit-chunk-size", "Set QR sizing..."),
                    )
            with section():
                yield group_label("Print setup")
                yield select_row("Kit type", "workspace-kit-variant-select", KIT_VARIANTS)
                yield select_row("Paper size", "workspace-kit-paper", PAPER_OPTIONS)
                yield select_row("Print design", "workspace-kit-design", DESIGN_OPTIONS)

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
        manifest = load_design_manifest_by_name(design_name)
        supported_names = supported_paper_size_names(
            design_name,
            doc_types=manifest.documents & KIT_RENDER_DOC_TYPES,
        )
        with paper_select.prevent(Select.Changed):
            paper_select.set_options(
                [(paper_size_display_name(name), name) for name in supported_names]
            )
        set_select(paper_select, value(layout, "paper"))
        set_select(self.query_one("#workspace-kit-design", Select), value(layout, "design"))

        output = group(presentation, "output")
        update_static_text(
            self.query_one("#kit-output-value", Static),
            first_value(output),
        )
        notice = None
        if output.status == "warning":
            notice = InlineNoticePresentation(
                "This PDF already exists and will be replaced after final review.",
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
                (
                    f"Custom sizing ({qr_summary}) can change page count and make codes "
                    "harder to scan."
                ),
                tone="warning",
            )
        self.query_one("#kit-qr-warning", InlineNotice).sync_presentation(qr_warning)
        update_static_text(
            self.query_one("#kit-chunk-size-value", Static),
            qr_summary,
        )
        self.query_one(f"#{KIT_ADVANCED_PANEL_ID}", Collapsible).set_class(
            qr.status == "warning",
            "workspace-panel-warning",
        )
        self.sync_advanced_panel(panel_title("QR sizing", qr_summary))
