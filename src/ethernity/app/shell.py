from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Label, OptionList

from ethernity.app.navigation import app_version_label, nav_options
from ethernity.app.widgets.preview_panel import PreviewPanel
from ethernity.app.widgets.task_canvas import TaskCanvas


def compose_app_shell() -> ComposeResult:
    with Horizontal(id="app-header"):
        yield Label("ETHERNITY", id="app-header-brand")
        yield Label("Paper backup and recovery", id="app-header-title")
        yield Label(app_version_label(), id="app-header-status")
    with Horizontal(id="shell"):
        with Vertical(id="nav"):
            yield Label("Workflows", id="nav-title")
            yield OptionList(
                *nav_options(),
                id="nav-list",
                compact=True,
            )
        with Vertical(id="workspace"):
            yield TaskCanvas(id="task-canvas")
        with Vertical(id="preview"):
            yield PreviewPanel(id="preview-panel")
    yield Footer()
