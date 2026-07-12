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
from textual.widgets import Button, LoadingIndicator, Static


class TaskActionBar(Widget):
    """Visible actions for the current task."""

    def compose(self) -> ComposeResult:
        with HorizontalGroup(id="canvas-action-row"):
            yield Static("", classes="canvas-action-spacer")
            yield Button("Diagnostics", id="canvas-internals", compact=True)
            yield Button("Review", id="canvas-primary", variant="primary", compact=True)

    def update_actions(
        self,
        *,
        primary_label: str,
        primary_enabled: bool,
        compact: bool,
        internals_visible: bool,
        running: bool,
        running_label: str | None,
    ) -> None:
        action_row = self.query_one("#canvas-action-row", HorizontalGroup)
        action_row.set_class(compact, "settings-mode")
        internals_button = self.query_one("#canvas-internals", Button)
        self._sync_loading_indicator(
            action_row,
            before=internals_button,
            visible=running and not compact,
        )
        internals_button.display = internals_visible and not compact and not running
        button = self.query_one("#canvas-primary", Button)
        button.disabled = running or not primary_enabled
        button.display = True
        button.variant = "primary"
        button.label = (running_label or "Task in progress") if running else primary_label

    def _sync_loading_indicator(
        self,
        action_row: HorizontalGroup,
        *,
        before: Button,
        visible: bool,
    ) -> None:
        loading = _existing_loading_indicator(self)
        if visible and loading is None:
            action_row.mount(LoadingIndicator(id="canvas-loading"), before=before)
        elif not visible and loading is not None:
            loading.remove()


def _existing_loading_indicator(widget: Widget) -> LoadingIndicator | None:
    for candidate in widget.query("#canvas-loading"):
        if isinstance(candidate, LoadingIndicator):
            return candidate
    return None
