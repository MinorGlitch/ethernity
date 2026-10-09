from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Label, ListView

from ethernity.app.navigation import app_version_label, nav_items
from ethernity.app.widgets.task_canvas import TaskCanvas


def compose_app_shell() -> ComposeResult:
    with Vertical(id="app-shell"):
        with Vertical(id="workbench-frame"):
            yield from _compose_workbench()
    yield Footer(show_command_palette=False, compact=True)


def _compose_workbench() -> ComposeResult:
    with Horizontal(id="app-header"):
        yield Label("ETHERNITY", id="app-header-brand")
        yield Label("Paper backup & recovery", id="app-header-title")
        yield Label(app_version_label(), id="app-header-status")
    with Horizontal(id="workbench-navigation"):
        yield Button(
            "1 Create backup",
            id="nav-create",
        )
        yield Button(
            "2 Restore files",
            id="nav-restore",
        )
        yield Button(
            "Manage",
            id="nav-manage",
        )
        yield Button(
            "Tools",
            id="nav-tools",
        )
    with Horizontal(id="shell"):
        with Vertical(id="nav-menu-anchor"):
            with Vertical(id="nav-menu", classes="popup-menu"):
                yield ListView(
                    *nav_items(),
                    id="nav-list",
                )
        with Vertical(id="workspace"):
            yield TaskCanvas(id="task-canvas")
