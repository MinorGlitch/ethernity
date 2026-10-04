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

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Grid, HorizontalGroup, Vertical, VerticalGroup, VerticalScroll
from textual.widget import Widget
from textual.widgets import Button, Static

from ethernity.app.execution import ReviewDetail
from ethernity.app.screens.modal import EthernityModalScreen
from ethernity.app.widgets.actions import ActionButton, modal_action_row
from ethernity.app.widgets.collapsible import collapsible_panel
from ethernity.tasks.models import (
    PreviewItem,
    TaskExecutionPlan,
    TaskIssue,
    TaskPreview,
    TaskValidation,
)


@dataclass(frozen=True, slots=True)
class ReviewEditRequest:
    """Return to one editable decision before preparing a fresh review."""

    section: str


class ReviewTaskScreen(EthernityModalScreen[bool | ReviewEditRequest]):
    """Focused final decision before a task writes files."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        *,
        title: str,
        validation: TaskValidation,
        preview: TaskPreview,
        plan: TaskExecutionPlan,
        execute_label: str,
        review_details: tuple[ReviewDetail, ...] = (),
    ) -> None:
        super().__init__()
        self._review_title = title
        self._validation = validation
        self._preview = preview
        self._plan = plan
        self._execute_label = execute_label
        self._review_details = review_details
        self._edit_sections: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        ready = self._validation.ready
        visible_issues = self._visible_issues()
        with Vertical(id="review-modal", classes="document " + ("ready" if ready else "missing")):
            with Vertical(id="review-header", classes="document-header"):
                yield Static(
                    self._review_title, id="review-title", markup=False, classes="screen-title"
                )

            with VerticalScroll(id="review-body", classes="document-body"):
                with Grid(id="review-overview", classes="detail-grid"):
                    for index, detail in enumerate(self._overview_details()):
                        yield from self._detail_widgets(detail, index)

                if self._plan.writes_files:
                    with VerticalGroup(id="review-output-list"):
                        yield Static("Output locations", classes="section-title", markup=False)
                        for line in self._output_lines():
                            yield Static(line, classes="detail-line", markup=False)

                if visible_issues:
                    with VerticalGroup(
                        id="review-attention",
                        classes=_attention_class(visible_issues),
                    ):
                        yield Static(
                            _attention_title(visible_issues),
                            classes="section-title",
                            markup=False,
                        )
                        for issue in visible_issues:
                            yield Static(
                                issue.message,
                                classes=f"review-notice review-notice-{issue.severity}",
                                markup=False,
                            )

                safety_lines = self._write_safety_lines()
                if safety_lines:
                    with VerticalGroup(id="review-write-safety"):
                        yield Static("Write safety", classes="section-title", markup=False)
                        for line in safety_lines:
                            yield Static(
                                _without_bullet(line),
                                classes="review-safety-line detail-line",
                                markup=False,
                            )

                with collapsible_panel(
                    "review-technical-details",
                    "Technical details",
                    classes="review-details-panel",
                    title_classes="review-details-title",
                ):
                    yield from self._technical_detail_widgets()

            yield modal_action_row(
                "review-actions",
                ActionButton("Back", "review-close"),
                ActionButton(
                    self._execute_label,
                    "review-execute",
                    variant="primary",
                    disabled=not ready,
                ),
            )

    def on_mount(self) -> None:
        selector = "#review-execute" if self._validation.ready else "#review-close"
        self.query_one(selector, Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        section = self._edit_sections.get(event.button.id or "")
        if section is not None:
            self.dismiss(ReviewEditRequest(section))
            return
        if event.button.id == "review-execute" and self._validation.ready:
            self.dismiss(True)
            return
        self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def _visible_issues(self) -> tuple[TaskIssue, ...]:
        return tuple(
            issue
            for issue in (*self._validation.issues, *self._preview.warnings)
            if issue.code != "FINAL_REVIEW_REQUIRED"
        )

    def _detail_widgets(self, detail: ReviewDetail, index: int) -> Iterable[Widget]:
        yield Static(detail.label, classes="detail-label", markup=False)
        value = Static(detail.value, classes="detail-value", markup=False)
        if detail.section is None:
            yield value
            return
        button_id = f"review-edit-{detail.section}-{index}"
        self._edit_sections[button_id] = detail.section
        button = Button("Edit", id=button_id, classes="review-detail-edit text-action")
        button.tooltip = f"Edit {detail.label.lower()}"
        yield HorizontalGroup(value, button, classes="review-detail-field")

    def _read_overview(self) -> str:
        if not self._plan.read_paths:
            return "No user files"
        return _path_overview(self._plan.read_paths)

    def _overview_details(self) -> tuple[ReviewDetail, ...]:
        if self._review_details:
            return self._review_details
        return (
            ReviewDetail("Action", self._execute_label),
            ReviewDetail("Source", self._read_overview()),
            ReviewDetail("Destination", self._output_overview()),
        )

    def _output_overview(self) -> str:
        if not self._plan.writes_files:
            return "No files will be written"
        if not self._plan.output_paths:
            return "No output selected"
        return _path_overview(self._plan.output_paths)

    def _technical_detail_widgets(self) -> ComposeResult:
        yield from _detail_section("Plan", (self._plan.summary,))
        if self._preview.items:
            yield from _detail_section(
                self._preview.title,
                tuple(_preview_detail(item) for item in self._preview.items),
            )
        if self._plan.read_paths:
            yield from _detail_section("Reads", self._read_lines())
        if self._plan.trust_notes:
            yield from _detail_section("Verification", self._plan.trust_notes)
        if self._plan.recovery_notes:
            yield from _detail_section("Recovery", self._plan.recovery_notes)

    def _output_lines(self) -> tuple[str, ...]:
        if not self._plan.writes_files:
            return ()
        if self._plan.output_paths:
            return tuple(str(path) for path in self._plan.output_paths)
        return ("No destination selected.",)

    def _read_lines(self) -> tuple[str, ...]:
        return tuple(str(path) for path in self._plan.read_paths)

    def _write_safety_lines(self) -> tuple[str, ...]:
        if not self._plan.writes_files:
            return ()
        if not self._plan.output_paths:
            return ("Choose a destination before writing files.",)

        existing_paths = [path for path in self._plan.output_paths if path.exists()]
        overwrite_notes = (
            (
                f"Existing destination: {_path_summary(existing_paths)}",
                "Existing files at the destination may be replaced.",
            )
            if existing_paths
            else ()
        )
        return (
            *self._plan.safety_notes,
            *overwrite_notes,
        )


def _preview_detail(item: PreviewItem) -> str:
    return f"{item.label}: {item.detail}" if item.detail else item.label


def _detail_section(title: str, lines: Sequence[str]) -> Iterable[Static]:
    yield Static(title, classes="detail-heading", markup=False)
    for line in lines:
        yield Static(_without_bullet(line), classes="detail-line", markup=False)


def _without_bullet(line: str) -> str:
    stripped = line.strip()
    return stripped[2:].lstrip() if stripped.startswith(("- ", "* ")) else stripped


def _path_overview(paths: Sequence[object]) -> str:
    return "\n".join(str(path) for path in paths)


def _path_summary(paths: Sequence[object]) -> str:
    visible = ", ".join(str(path) for path in paths[:3])
    if len(paths) > 3:
        return f"{visible}, and {len(paths) - 3} more"
    return visible


def _attention_class(issues: tuple[TaskIssue, ...]) -> str:
    severity = "error" if any(issue.severity == "error" for issue in issues) else "warning"
    return f"review-attention review-attention-{severity}"


def _attention_title(issues: tuple[TaskIssue, ...]) -> str:
    if any(issue.severity == "error" for issue in issues):
        return "Fix before continuing"
    return "Warning" if len(issues) == 1 else "Warnings"
