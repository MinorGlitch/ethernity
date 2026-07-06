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

"""Reusable task-workspace primitives for guided CLI flows."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import questionary
from rich.table import Table
from rich.text import Text

from ethernity.cli.shared.ui.prompts_core import prompt_choice_list
from ethernity.cli.shared.ui.renderables import panel
from ethernity.cli.shared.ui.runtime import console
from ethernity.cli.shared.ui.state import UIContext

WorkspaceStatus = Literal["missing", "ready", "warning", "blocked"]


@dataclass(frozen=True)
class WorkspaceSection:
    """A user-editable section in a guided task workspace."""

    key: str
    title: str
    status: WorkspaceStatus
    summary: str
    action_label: str | None = None
    detail: str | None = None

    @property
    def can_proceed(self) -> bool:
        return self.status in {"ready", "warning"}

    @property
    def is_actionable(self) -> bool:
        return self.action_label is not None


def _status_label(status: WorkspaceStatus) -> str:
    labels = {
        "missing": "needed",
        "ready": "ready",
        "warning": "check",
        "blocked": "blocked",
    }
    return labels[status]


def _status_style(status: WorkspaceStatus) -> str:
    styles = {
        "missing": "warning",
        "ready": "success",
        "warning": "warning",
        "blocked": "error",
    }
    return styles[status]


def workspace_ready(sections: Sequence[WorkspaceSection]) -> bool:
    """Return whether every required section can move to final review."""

    return all(section.can_proceed for section in sections)


def first_blocked_section(sections: Sequence[WorkspaceSection]) -> WorkspaceSection | None:
    """Return the first section that prevents final review."""

    for section in sections:
        if not section.can_proceed:
            return section
    return None


def build_workspace_table(sections: Sequence[WorkspaceSection]) -> Table:
    """Build a compact section status table for a task workspace."""

    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column("Status", no_wrap=True)
    table.add_column("Section", style="bold", no_wrap=True)
    table.add_column("Summary")
    for section in sections:
        status = Text(_status_label(section.status), style=_status_style(section.status))
        summary = section.summary
        if section.detail:
            summary = f"{summary} {section.detail}"
        table.add_row(status, section.title, summary)
    return table


def print_workspace(title: str, sections: Sequence[WorkspaceSection], *, quiet: bool) -> None:
    """Render the current task workspace state."""

    if quiet:
        return
    console.print(panel(title, build_workspace_table(sections)))


def prompt_workspace_action(
    title: str,
    sections: Sequence[WorkspaceSection],
    *,
    proceed_label: str,
    proceed_value: str = "review",
    default: str | None = None,
    help_text: str | None = None,
    context: UIContext | None = None,
) -> str:
    """Prompt for the next workspace action.

    The returned value is either a section key, ``proceed_value``, or ``cancel``.
    """

    items: list[tuple[str, str] | questionary.Separator | questionary.Choice] = []
    ready = workspace_ready(sections)
    blocker: WorkspaceSection | None = None
    if ready:
        items.append(questionary.Choice(proceed_label, value=proceed_value))
        items.append(questionary.Separator(" "))
    else:
        blocker = first_blocked_section(sections)
        if blocker is not None:
            items.append(
                questionary.Choice(
                    blocker.action_label or f"Fix {blocker.title.lower()}",
                    value=blocker.key,
                    description=blocker.summary,
                )
            )
            items.append(questionary.Separator(" "))

    for section in sections:
        if not ready and blocker is not None and section.key == blocker.key:
            continue
        if not section.is_actionable:
            continue
        action_label = section.action_label or f"Edit {section.title.lower()}"
        items.append(
            questionary.Choice(
                action_label,
                value=section.key,
                description=f"{_status_label(section.status)} - {section.summary}",
            )
        )
    items.append(questionary.Separator(" "))
    items.append(questionary.Choice("Cancel", value="cancel"))

    return prompt_choice_list(
        items,
        default=default or (proceed_value if ready else None),
        title=title,
        help_text=help_text,
        context=context,
    )


__all__ = [
    "WorkspaceSection",
    "WorkspaceStatus",
    "build_workspace_table",
    "first_blocked_section",
    "print_workspace",
    "prompt_workspace_action",
    "workspace_ready",
]
