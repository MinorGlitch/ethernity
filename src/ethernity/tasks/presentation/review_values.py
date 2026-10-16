"""Formatting shared by task-specific review presenters."""

from __future__ import annotations

from ethernity.page_sizes import paper_size_display_name
from ethernity.tasks.models import TaskExecutionPlan


def destination_summary(plan: TaskExecutionPlan) -> str:
    if not plan.writes_files:
        return "No files will be written"
    if not plan.output_paths:
        return "No destination"
    return "\n".join(str(path.expanduser().absolute()) for path in plan.output_paths)


def layout_summary(paper_size: str, design: str) -> str:
    return f"{paper_size_display_name(paper_size)}, {design.title()}"
