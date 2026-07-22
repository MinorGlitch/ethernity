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

from dataclasses import dataclass

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, MarkdownViewer, Static

from ethernity.app.screens.modal import EthernityModalScreen
from ethernity.app.widgets.actions import ActionButton, modal_action_row


@dataclass(frozen=True)
class HelpSection:
    title: str
    body: str
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class HelpShortcut:
    keys: tuple[str, ...]
    label: str


@dataclass(frozen=True)
class HelpMode:
    key: str
    summary: str
    sections: tuple[HelpSection, ...]
    shortcuts: tuple[HelpShortcut, ...]


@dataclass(frozen=True)
class HelpContent:
    title: str
    intro: str
    mode: HelpMode


class HelpScreen(EthernityModalScreen[None]):
    """Contextual help for the active workflow."""

    BINDINGS = [("escape", "close", "Close")]

    def __init__(self, content: HelpContent) -> None:
        super().__init__()
        self._content = content

    def compose(self) -> ComposeResult:
        with Vertical(id="help-modal"):
            yield Static(self._content.title, id="help-title")
            yield Static(self._content.intro, id="help-intro")
            yield Static(
                _shortcut_text(self._content.mode.shortcuts),
                id="help-shortcuts",
                markup=False,
            )
            yield MarkdownViewer(
                _help_markdown(self._content),
                id="help-body",
                show_table_of_contents=False,
                open_links=False,
            )
            yield modal_action_row(
                "help-actions",
                ActionButton("Close", "help-close"),
            )

    def on_mount(self) -> None:
        self.query_one("#help-body", MarkdownViewer).document.focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "help-close":
            return
        event.stop()
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


def _help_markdown(content: HelpContent) -> str:
    return "\n\n".join(_markdown_section(section) for section in content.mode.sections)


def _markdown_section(section: HelpSection) -> str:
    notes = f"\n\n{_markdown_items(section.notes)}" if section.notes else ""
    return f"### {section.title}\n{section.body}{notes}"


def _markdown_items(items: tuple[str, ...]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _shortcut_text(shortcuts: tuple[HelpShortcut, ...]) -> Text:
    text = Text()
    for index, shortcut in enumerate(shortcuts):
        if index:
            text.append("\n" if index % 3 == 0 else "   ")
        text.append("/".join(shortcut.keys), style="bold")
        text.append(f": {shortcut.label}")
    return text
