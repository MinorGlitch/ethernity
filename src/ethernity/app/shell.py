from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Label, ListView

from ethernity.app.navigation import app_version_label, nav_items
from ethernity.app.widgets.task_canvas import TaskCanvas


def compose_app_shell() -> ComposeResult:
    with Horizontal(id="app-header"):
        yield Label("ETHERNITY", id="app-header-brand")
        yield Label("Paper backup and recovery", id="app-header-title")
        yield Label(app_version_label(), id="app-header-status")
    with Horizontal(id="shell"):
        with Vertical(id="nav"):
            nav_button = Button("☰", id="nav-strip", compact=True)
            nav_button.tooltip = "Open workflow navigation"
            yield nav_button
            with Vertical(id="nav-drawer"):
                yield Label("Workflows", id="nav-title")
                yield ListView(
                    *nav_items(),
                    id="nav-list",
                )
        with Vertical(id="workspace"):
            yield TaskCanvas(id="task-canvas")
    yield Footer(show_command_palette=False, compact=True)
