from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Label, ListView

from ethernity.app.navigation import NAV_LABELS, app_version_label, nav_items
from ethernity.app.widgets.navigation import NavigationBar
from ethernity.app.widgets.task_canvas import TaskCanvas


def compose_app_shell() -> ComposeResult:
    with Vertical(id="app-shell"):
        with Vertical(id="workbench-frame"):
            yield from _compose_workbench()


def _compose_workbench() -> ComposeResult:
    with Horizontal(id="app-header"):
        yield Label("ETHERNITY", id="app-header-brand")
        yield Label("Paper backup & recovery", id="app-header-title")
        yield Label(app_version_label(), id="app-header-status")
    with NavigationBar(id="workbench-navigation"):
        yield Button(
            f"1 {NAV_LABELS['backup']}",
            id="nav-create",
        )
        yield Button(
            f"2 {NAV_LABELS['restore']}",
            id="nav-restore",
        )
        yield Button(
            "Manage",
            id="nav-manage",
        )
        yield Button(
            NAV_LABELS["kit"],
            id="nav-kit",
        )
        yield Button(
            NAV_LABELS["settings"],
            id="nav-settings",
        )
        yield Button(
            "Help", id="nav-help", action="app.help", tooltip="Help and keyboard shortcuts (?)"
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
