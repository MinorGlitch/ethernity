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

import json

from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Button,
    Label,
    RichLog,
    Static,
    Switch,
    TabbedContent,
    TabPane,
)

from ethernity.app.screens.modal import EthernityModalScreen
from ethernity.app.widgets.actions import ActionButton, modal_action_row
from ethernity.tasks.models import TaskDiagnostics


class DiagnosticsScreen(EthernityModalScreen[None]):
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
                    yield Label("Show sensitive values", id="diagnostics-reveal-label")
                    yield Switch(False, animate=False, id="diagnostics-reveal")
            with TabbedContent(
                initial=_diagnostics_tab_id(0),
                id="diagnostics-tabs",
            ):
                for index, block in enumerate(self._diagnostics.blocks):
                    with TabPane(block.title, id=_diagnostics_tab_id(index)):
                        yield RichLog(
                            id=_diagnostics_log_id(index),
                            classes="diagnostics-internals",
                            highlight=True,
                            markup=False,
                            wrap=False,
                        )
                if not self._diagnostics.blocks:
                    with TabPane("Diagnostics", id=_diagnostics_tab_id(0)):
                        yield RichLog(
                            id=_diagnostics_log_id(0),
                            classes="diagnostics-internals",
                            highlight=True,
                            markup=False,
                            wrap=False,
                        )
            yield modal_action_row(
                "diagnostics-actions",
                ActionButton("Close", "diagnostics-close"),
            )

    def on_mount(self) -> None:
        self._refresh_internals()
        self._focus_active_log()

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if event.tabbed_content.id != "diagnostics-tabs":
            return
        event.stop()
        self._focus_active_log()

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
        if not self._diagnostics.blocks:
            log = self.query_one(f"#{_diagnostics_log_id(0)}", RichLog)
            log.clear()
            log.write("No diagnostic data for these inputs.")
            return
        for index, block in enumerate(self._diagnostics.blocks):
            log = self.query_one(f"#{_diagnostics_log_id(index)}", RichLog)
            log.clear()
            content = block.display_content(reveal_sensitive=self._reveal_sensitive)
            if _looks_like_json(content):
                log.write(Syntax(content, "json", word_wrap=False, background_color="default"))
            else:
                log.write(content)

    def _focus_active_log(self) -> None:
        tabs = self.query_one("#diagnostics-tabs", TabbedContent)
        active_tab = tabs.active or _diagnostics_tab_id(0)
        try:
            index = int(active_tab.rsplit("-", 1)[1])
        except ValueError:
            index = 0
        self.query_one(f"#{_diagnostics_log_id(index)}", RichLog).focus()


def _diagnostics_tab_id(index: int) -> str:
    return f"diagnostics-tab-{index}"


def _diagnostics_log_id(index: int) -> str:
    return f"diagnostics-log-{index}"


def _looks_like_json(content: str) -> bool:
    stripped = content.strip()
    if not stripped.startswith(("{", "[")):
        return False
    try:
        json.loads(stripped)
    except ValueError:
        return False
    return True
