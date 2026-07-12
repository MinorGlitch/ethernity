from __future__ import annotations

from textual.binding import Binding, BindingType

from ethernity.app.workflow_registry import WORKFLOWS

APP_TITLE = "ETHERNITY"
APP_SUB_TITLE = "Paper backup and recovery"

APP_BINDINGS: list[BindingType] = [
    Binding("q", "quit", "Quit"),
    Binding("escape", "close_navigation", "Close navigation", show=False),
    Binding("?", "help", "Help"),
    # The sticky task action already exposes review in every workflow, while
    # Settings has no review action. Keep the shortcut without advertising an
    # inapplicable global command in the footer.
    Binding("ctrl+r", "review", "Review", show=False),
    Binding("ctrl+p", "command_palette", "Command palette", show=False),
    Binding("j", "move_down", "Down", show=False),
    Binding("down", "move_down", "Down", show=False),
    Binding("k", "move_up", "Up", show=False),
    Binding("up", "move_up", "Up", show=False),
    Binding("h", "move_left", "Navigation", show=False),
    Binding("left", "move_left", "Left", show=False),
    Binding("l", "move_right", "Workspace", show=False),
    Binding("right", "move_right", "Right", show=False),
    *(
        Binding(
            workflow.shortcut,
            f"show_task('{workflow.key}')",
            workflow.title,
            show=False,
        )
        for workflow in WORKFLOWS
    ),
]
