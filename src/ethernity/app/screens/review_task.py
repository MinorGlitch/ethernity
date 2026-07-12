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

from textual.app import ComposeResult
from textual.containers import Grid, Vertical, VerticalGroup, VerticalScroll
from textual.widgets import Button, Rule, Static

from ethernity.app.execution import ReviewDecisionFact
from ethernity.app.screens.modal import EthernityModalScreen
from ethernity.app.widgets.actions import ActionButton, modal_action_row
from ethernity.app.widgets.collapsible import collapsible_panel
from ethernity.tasks.file_summary import display_path
from ethernity.tasks.models import (
    PreviewItem,
    TaskExecutionPlan,
    TaskIssue,
    TaskPreview,
    TaskValidation,
)


class ReviewTaskScreen(EthernityModalScreen[bool]):
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
        decision_facts: tuple[ReviewDecisionFact, ...] = (),
    ) -> None:
        super().__init__()
        self._review_title = title
        self._validation = validation
        self._preview = preview
        self._plan = plan
        self._execute_label = execute_label
        self._decision_facts = decision_facts

    def compose(self) -> ComposeResult:
        ready = self._validation.ready
        visible_issues = self._visible_issues()
        with Vertical(id="review-modal", classes="ready" if ready else "missing"):
            with Vertical(id="review-header"):
                yield Static(self._review_title, id="review-title", markup=False)

            with VerticalScroll(id="review-body"):
                with VerticalGroup(id="review-overview"):
                    with Grid(id="review-key-facts"):
                        for fact in self._overview_facts():
                            yield from _fact_widgets(fact.label, fact.value)

                if visible_issues:
                    yield Rule(classes="review-section-rule")
                    with VerticalGroup(
                        id="review-attention",
                        classes=_attention_class(visible_issues),
                    ):
                        yield Static(
                            _attention_title(visible_issues),
                            classes="review-section-title",
                            markup=False,
                        )
                        for issue in visible_issues:
                            yield Static(
                                issue.message,
                                classes=f"review-notice review-notice-{issue.severity}",
                                markup=False,
                            )

                yield Rule(classes="review-section-rule")
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

    def _read_overview(self) -> str:
        if not self._plan.read_paths:
            return "No user files"
        return _path_overview(self._plan.read_paths)

    def _overview_facts(self) -> tuple[ReviewDecisionFact, ...]:
        if self._decision_facts:
            return self._decision_facts
        return (
            ReviewDecisionFact("Action", self._execute_label),
            ReviewDecisionFact("Source", self._read_overview()),
            ReviewDecisionFact("Destination", self._output_overview()),
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
        if self._plan.writes_files:
            yield from _detail_section("Writes", self._output_lines())
            yield from _detail_section("Write safety", self._write_safety_lines())
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
        existing_summary = (
            f"Existing path: {_path_summary(existing_paths)}"
            if existing_paths
            else "The destination does not exist yet."
        )
        return (
            existing_summary,
            *self._plan.safety_notes,
            "Existing files at the destination may be replaced.",
            "A failed write may leave partial files.",
        )


def _fact_widgets(label: str, value: str) -> Iterable[Static]:
    yield Static(label, classes="review-fact-label", markup=False)
    yield Static(value, classes="review-fact-value", markup=False)


def _preview_detail(item: PreviewItem) -> str:
    return f"{item.label}: {item.detail}" if item.detail else item.label


def _detail_section(title: str, lines: Sequence[str]) -> Iterable[Static]:
    yield Static(title, classes="review-detail-title", markup=False)
    for line in lines:
        yield Static(_without_bullet(line), classes="review-detail-line", markup=False)


def _without_bullet(line: str) -> str:
    stripped = line.strip()
    return stripped[2:].lstrip() if stripped.startswith(("- ", "* ")) else stripped


def _path_overview(paths: Sequence[object]) -> str:
    first = display_path(str(paths[0]), max_chars=72)
    if len(paths) == 1:
        return first
    return f"{first} and {len(paths) - 1} more"


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
