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
from textual.containers import HorizontalGroup
from textual.widget import Widget
from textual.widgets import Button, Static


class TaskActionBar(Widget):
    """Visible actions for the current task."""

    def compose(self) -> ComposeResult:
        with HorizontalGroup(id="canvas-action-row"):
            yield Static("", id="canvas-action-spacer")
            yield Button("Review", id="canvas-primary", variant="primary")

    def update_actions(
        self,
        *,
        primary_label: str,
        primary_enabled: bool,
        blocked: bool,
        compact: bool,
    ) -> None:
        self.query_one("#canvas-action-row", HorizontalGroup).set_class(compact, "settings-mode")
        self.query_one("#canvas-action-spacer", Static).display = True
        button = self.query_one("#canvas-primary", Button)
        button.label = primary_label
        button.disabled = not primary_enabled
        button.display = True
        button.variant = "warning" if blocked else "primary"
