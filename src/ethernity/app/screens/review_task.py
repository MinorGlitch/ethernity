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
from textual.containers import Horizontal, HorizontalGroup, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from ethernity.tasks.models import (
    PreviewItem,
    TaskExecutionPlan,
    TaskIssue,
    TaskPreview,
    TaskSection,
    TaskValidation,
)


class ReviewTaskScreen(ModalScreen[bool]):
    """Final task review before a write action."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        *,
        title: str,
        validation: TaskValidation,
        preview: TaskPreview,
        plan: TaskExecutionPlan,
        execute_label: str,
    ) -> None:
        super().__init__()
        self._review_title = title
        self._validation = validation
        self._preview = preview
        self._plan = plan
        self._execute_label = execute_label

    def compose(self) -> ComposeResult:
        ready = self._validation.ready
        visible_issues = self._visible_issues()
        with Vertical(id="review-modal", classes="ready" if ready else "missing"):
            with Horizontal(id="review-header"):
                with Vertical(id="review-heading"):
                    yield Static("Review", id="review-kicker")
                    yield Static(self._review_title, id="review-title")
                with Vertical(id="review-status-card"):
                    yield Static(
                        self._status_text(ready),
                        id="review-status",
                        classes="ready" if ready else "missing",
                    )
                    yield Static(self._readiness_text(), id="review-summary")
            with VerticalScroll(id="review-body"):
                if visible_issues:
                    with Vertical(id="review-attention", classes="review-panel"):
                        yield Static("Fix before running", classes="review-section-title")
                        for issue in visible_issues:
                            yield _issue_row(issue)
                with Horizontal(id="review-columns"):
                    with Vertical(id="review-checklist", classes="review-panel"):
                        yield Static("Checklist", classes="review-section-title")
                        for section in _ordered_sections(self._validation.sections):
                            yield _section_row(section)
                    with Vertical(id="review-details"):
                        with Vertical(classes="review-panel review-output-panel"):
                            yield Static("Destination", classes="review-section-title")
                            yield Static(
                                "Will write files"
                                if self._plan.writes_files
                                else "Runs without writing files",
                                classes="review-output-intent",
                            )
                            for line in self._output_lines():
                                yield Static(line, classes="review-output-line")
                        with Vertical(classes="review-panel review-preview-panel"):
                            yield Static(self._preview.title, classes="review-section-title")
                            if self._preview.items:
                                for item in self._preview.items:
                                    yield _preview_item_row(item)
                            else:
                                yield Static("Nothing to preview", classes="review-muted")
            with Horizontal(id="review-actions"):
                yield Static("", id="review-action-spacer")
                yield Button("Back", id="review-close", compact=True)
                yield Button(
                    self._execute_label,
                    id="review-execute",
                    variant="primary",
                    disabled=not ready,
                    compact=True,
                )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "review-execute" and self._validation.ready:
            self.dismiss(True)
            return
        self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def _output_lines(self) -> list[str]:
        if not self._plan.writes_files:
            return ["No files will be written"]
        if self._plan.output_paths:
            return [str(path) for path in self._plan.output_paths]
        return ["No output path selected yet"]

    def _visible_issues(self) -> tuple[TaskIssue, ...]:
        return tuple(
            issue
            for issue in (*self._validation.issues, *self._preview.warnings)
            if issue.code != "FINAL_REVIEW_REQUIRED"
        )

    def _readiness_text(self) -> str:
        total = max(len(self._validation.sections), 1)
        ready = sum(1 for section in self._validation.sections if section.status == "ready")
        return f"{ready}/{total} ready"

    def _status_text(self, ready: bool) -> str:
        if not ready:
            return "Needs attention before writing"
        if not self._plan.writes_files:
            return "Ready to run"
        return "Ready to write files"


def _section_row(section: TaskSection) -> HorizontalGroup:
    return HorizontalGroup(
        Static(_status_label(section.status), classes=f"review-chip review-{section.status}"),
        Static(section.title, classes="review-row-title"),
        Static(section.summary, classes="review-row-summary"),
        classes=f"review-row review-{section.status}",
    )


def _preview_item_row(item: PreviewItem) -> HorizontalGroup:
    return HorizontalGroup(
        Static(item.label, classes="review-item-label"),
        Static(item.detail or "", classes="review-item-detail"),
        classes="review-row review-item-row",
    )


def _issue_row(issue: TaskIssue) -> HorizontalGroup:
    return HorizontalGroup(
        Static(_severity_label(issue.severity), classes=f"review-chip review-{issue.severity}"),
        Static(issue.message, classes="review-issue-message"),
        classes=f"review-row review-issue-row review-{issue.severity}",
    )


def _status_label(status: str) -> str:
    if status == "ready":
        return "Ready"
    if status == "warning":
        return "Check"
    if status == "blocked":
        return "Blocked"
    return "Missing"


def _severity_label(severity: str) -> str:
    if severity == "info":
        return "Info"
    if severity == "warning":
        return "Check"
    return "Required"


def _ordered_sections(sections: tuple[TaskSection, ...]) -> tuple[TaskSection, ...]:
    return tuple(sorted(sections, key=lambda section: _section_priority(section.status)))


def _section_priority(status: str) -> int:
    priorities = {
        "blocked": 0,
        "missing": 1,
        "warning": 2,
        "ready": 3,
    }
    return priorities.get(status, 4)
