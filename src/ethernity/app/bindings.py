from __future__ import annotations

from textual.binding import Binding, BindingType

APP_TITLE = "ETHERNITY"
APP_SUB_TITLE = "Paper backup and recovery"

APP_BINDINGS: list[BindingType] = [
    Binding("q", "quit", "Quit"),
    Binding("?", "help", "Help"),
    Binding("ctrl+r", "review", "Review"),
    Binding("j", "nav_next", "Next"),
    Binding("down", "nav_next", "Next", show=False),
    Binding("k", "nav_previous", "Previous"),
    Binding("up", "nav_previous", "Previous", show=False),
    Binding("h", "focus_nav", "Workflows"),
    Binding("left", "focus_nav", "Workflows", show=False),
    Binding("l", "focus_workspace", "Main"),
    Binding("right", "focus_workspace", "Main", show=False),
    Binding("1", "show_backup", "Backup", show=False),
    Binding("2", "show_restore", "Restore", show=False),
    Binding("3", "show_add_files", "Add files", show=False),
    Binding("4", "show_rebuild", "Rebuild", show=False),
    Binding("5", "show_replace_recovery_docs", "Replace recovery", show=False),
    Binding("6", "show_kit", "Kit", show=False),
    Binding("7", "show_doctor", "Doctor", show=False),
    Binding("8", "show_settings", "Settings", show=False),
    Binding("i", "edit_primary", "Input", show=False),
    Binding("o", "edit_output", "Output", show=False),
    Binding("p", "edit_passphrase", "Passphrase", show=False),
    Binding("ctrl+j", "execute_current", "Run", show=False),
    Binding("c", "clear_task", "Clear", show=False),
]
