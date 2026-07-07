#!/usr/bin/env python3
# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.widget import Widget
from textual.widgets import Button, Label, OptionList, Static
from textual.widgets.option_list import Option

from ethernity.tasks.models import (
    PreviewItem,
    TaskExecutionResult,
    TaskIssue,
    TaskPreview,
    TaskValidation,
)


class PreviewPanel(Widget):
    """Right-side consequence and issue panel."""

    def compose(self) -> ComposeResult:
        with Vertical(id="preview-panel-shell"):
            yield Label("Summary", id="preview-eyebrow")
            yield Static("", id="preview-title")
            yield Label("Blockers", id="preview-issues-title")
            yield OptionList(id="preview-issues", compact=True)
            yield OptionList(id="preview-items", compact=True)
            yield Static("", id="preview-result")
            with Horizontal(id="preview-actions"):
                yield Button("Internals", id="preview-diagnostics")

    def update_preview(
        self,
        *,
        preview: TaskPreview,
        validation: TaskValidation,
        result: TaskExecutionResult | None,
        diagnostics_available: bool,
    ) -> None:
        issues = (
            *[warning for warning in preview.warnings if warning.code != "FINAL_REVIEW_REQUIRED"],
            *validation.issues,
        )
        self.query_one("#preview-title", Static).update(_summary_title(preview, validation))
        self.query_one("#preview-issues-title", Label).display = bool(issues)
        self.query_one("#preview-issues", OptionList).display = bool(issues)
        self.query_one("#preview-issues", OptionList).set_options(
            [_issue_option(issue, index) for index, issue in enumerate(issues)]
        )
        items = list(preview.items)
        if not validation.ready and validation.issues:
            first_issue = validation.issues[0]
            items.insert(
                0,
                PreviewItem(label="Next required action", detail=first_issue.message),
            )
        self.query_one("#preview-items", OptionList).set_options(
            [
                Option(_preview_item_text(item.label, item.detail), id=f"preview-{index}")
                for index, item in enumerate(items)
            ]
        )
        self.query_one("#preview-result", Static).update(_result_text(result))
        diagnostics_button = self.query_one("#preview-diagnostics", Button)
        diagnostics_button.display = diagnostics_available
        diagnostics_button.disabled = not diagnostics_available


def _preview_item_text(label: str, detail: str | None) -> Content:
    if not detail:
        return Content.assemble((label, "bold"))
    return Content.assemble((label, "bold"), "\n", (detail, "dim"))


def _issue_option(issue: TaskIssue, index: int) -> Option:
    style = "$text-error" if issue.severity == "error" else "$text-warning"
    label = "Required" if issue.severity == "error" else "Warning"
    return Option(
        Content.assemble((label, style), " ", issue.message),
        id=f"issue-{index}",
    )


def _summary_title(preview: TaskPreview, validation: TaskValidation) -> str:
    if validation.ready:
        return preview.title
    return "Next safe step"


def _result_text(result: TaskExecutionResult | None) -> str:
    if result is None:
        return ""
    lines = [result.message]
    lines.extend(str(path) for path in result.output_paths)
    return "\n".join(lines)
