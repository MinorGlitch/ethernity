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

from rich.console import Console
from rich.table import Table

from ethernity.tasks.models import TaskExecutionResult, TaskPreview, TaskValidation

console = Console()


def print_task_validation(validation: TaskValidation) -> None:
    table = Table("Section", "Status", "Summary", show_lines=False)
    for section in validation.sections:
        table.add_row(section.title, section.status, section.summary)
    console.print(table)
    for issue in validation.issues:
        style = "yellow" if issue.severity == "warning" else "red"
        console.print(f"[{style}]{issue.message}[/{style}]")


def print_task_preview(preview: TaskPreview) -> None:
    table = Table(preview.title, "Detail", show_lines=False)
    for item in preview.items:
        table.add_row(item.label, item.detail or "")
    console.print(table)
    for warning in preview.warnings:
        console.print(f"[yellow]{warning.message}[/yellow]")


def print_task_execution_result(result: TaskExecutionResult) -> None:
    style = "green" if result.ok else "red"
    console.print(f"[{style}]{result.message}[/{style}]")
    if result.details:
        details = Table("Result", "Value", show_lines=False)
        for detail in result.details:
            value = (
                ", ".join(detail.value)
                if isinstance(detail.value, tuple)
                else ""
                if detail.value is None
                else str(detail.value)
            )
            details.add_row(detail.label, value)
        console.print(details)
    if result.output_paths:
        table = Table("Written files", show_lines=False)
        for path in result.output_paths:
            table.add_row(str(path))
        console.print(table)
    for step in result.next_steps:
        console.print(f"[yellow]{step}[/yellow]")
