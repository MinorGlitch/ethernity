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
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Label,
    RichLog,
    Static,
    Switch,
)

from ethernity.tasks.models import TaskDiagnostics


class DiagnosticsScreen(ModalScreen[None]):
    """On-demand advanced diagnostics for the current task."""

    BINDINGS = [("escape", "close", "Close")]

    def __init__(self, diagnostics: TaskDiagnostics) -> None:
        super().__init__()
        self._diagnostics = diagnostics
        self._reveal_sensitive = False

    def compose(self) -> ComposeResult:
        with Vertical(id="diagnostics-modal"):
            yield Static(self._diagnostics.title, id="diagnostics-title")
            if self._diagnostics.has_sensitive_values:
                with Horizontal(id="diagnostics-toolbar"):
                    yield Label("Reveal secrets", id="diagnostics-reveal-label")
                    yield Switch(False, animate=False, id="diagnostics-reveal")
            yield RichLog(
                id="diagnostics-internals",
                highlight=False,
                markup=False,
                wrap=False,
            )
            with Horizontal(id="diagnostics-actions"):
                yield Static("", id="diagnostics-action-spacer")
                yield Button("Close", id="diagnostics-close", compact=True)

    def on_mount(self) -> None:
        self._refresh_internals()
        self.query_one("#diagnostics-internals", RichLog).focus()

    def on_switch_changed(self, event: Switch.Changed) -> None:
        if event.switch.id != "diagnostics-reveal":
            return
        event.stop()
        self._reveal_sensitive = event.value
        self._refresh_internals()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "diagnostics-close":
            event.stop()
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)

    def _refresh_internals(self) -> None:
        log = self.query_one("#diagnostics-internals", RichLog)
        log.clear()
        if not self._diagnostics.blocks:
            return
        for block in self._diagnostics.blocks:
            log.write(Content.assemble((block.title, "bold $text-primary")))
            log.write(block.display_content(reveal_sensitive=self._reveal_sensitive))
            log.write("")
