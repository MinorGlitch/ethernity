from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, cast

from textual.containers import HorizontalGroup
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView

from ethernity.app.task_catalog import TASK_TITLES
from ethernity.app.workflow_registry import (
    WORKFLOWS,
    workflow_definition,
)
from ethernity.tasks.models import TaskIssue
from ethernity.tasks.task_types import TaskKey
from ethernity.version import get_ethernity_version

NavMenu = Literal["manage", "tools"]
NAV_MENUS: dict[NavMenu, tuple[TaskKey, ...]] = {
    "manage": ("add_files", "rebuild", "replace_recovery_docs"),
    "tools": ("kit", "settings"),
}
NAV_NUMBERS: dict[TaskKey, str] = {workflow.key: workflow.shortcut for workflow in WORKFLOWS}
NAV_LABELS: dict[TaskKey, str] = {
    "backup": "Create backup",
    "restore": "Restore files",
    "add_files": "Add files",
    "rebuild": "Rebuild backup",
    "replace_recovery_docs": "Replace sheets",
    "kit": "Offline recovery kit",
    "settings": "Settings",
}


async def run_directional_widget_binding(focused: Widget | None, key: str) -> bool:
    """Give hjkl the focused control's arrow behavior, without replaying container bindings."""

    if focused is None:
        return False
    active_binding = focused.screen.active_bindings.get(key)
    if active_binding is None or not active_binding.enabled or active_binding.node is not focused:
        return False
    return await focused.app.run_action(active_binding.binding.action, default_namespace=focused)


def nav_items(active_task: TaskKey | None = None) -> tuple[ListItem, ...]:
    return tuple(
        _nav_item(task_key, active_task)
        for task_keys in NAV_MENUS.values()
        for task_key in task_keys
    )


NavTaskState = Literal["", "in-progress", "ready", "attention"]


def sync_nav_active(
    nav: ListView,
    active_task: TaskKey,
    task_states: Mapping[TaskKey, NavTaskState] | None = None,
    *,
    menu: NavMenu = "manage",
) -> None:
    for item in nav.query(ListItem):
        task_key = _nav_item_task(item)
        if task_key is None:
            continue
        active = task_key == active_task
        visible = task_key in NAV_MENUS[menu]
        item.display = visible
        item.disabled = not visible
        item.set_class(active, "active")
        item.query_one(".nav-row-marker", Label).update(">" if active else "")
        state = task_states.get(task_key, "") if task_states is not None else ""
        state_label = item.query_one(".nav-row-state", Label)
        state_label.update({"in-progress": "WIP", "ready": "OK", "attention": "FIX"}.get(state, ""))
        state_label.tooltip = {
            "in-progress": "Work in progress",
            "ready": "Ready for final review",
            "attention": "Fix required inputs",
        }.get(state)
    if nav.highlighted_child is None or nav.highlighted_child.disabled:
        nav.index = next((index for index, item in enumerate(nav.children) if item.display), None)


def workspace_focus_selector(task: TaskKey) -> str:
    return workflow_definition(task).initial_focus


def blocker_focus_selector(task: TaskKey, section: str | None) -> str:
    return workflow_definition(task).focus_for_section(section)


def issue_focus_selector(task: TaskKey, issue: TaskIssue | None) -> str:
    if issue is None:
        return workspace_focus_selector(task)
    return workflow_definition(task).focus_for_issue(issue.code, issue.section)


def app_version_label() -> str:
    version = get_ethernity_version()
    return f"v{version}" if version else "dev"


def _nav_item_task(item: ListItem) -> TaskKey | None:
    item_id = item.id
    if item_id in TASK_TITLES:
        return cast(TaskKey, item_id)
    return None


def _nav_item(task_key: TaskKey, active_task: TaskKey | None) -> ListItem:
    active = task_key == active_task
    return ListItem(
        HorizontalGroup(
            Label(">" if active else "", classes="nav-row-marker"),
            Label(NAV_NUMBERS[task_key], classes="nav-row-number"),
            Label(NAV_LABELS[task_key], classes="nav-row-label"),
            Label("", classes="nav-row-state"),
            classes="nav-row",
        ),
        id=task_key,
        classes="popup-choice active" if active else "popup-choice",
    )
