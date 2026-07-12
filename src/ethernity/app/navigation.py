from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, cast

from textual.containers import HorizontalGroup
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView

from ethernity.app.app_types import ActiveTask
from ethernity.app.task_catalog import NAV_OPTION_INDEX, TASK_TITLES
from ethernity.app.workflow_registry import (
    WORKFLOW_GROUPS,
    workflow_definition,
    workflows_in_group,
)
from ethernity.tasks.models import TaskIssue
from ethernity.version import get_ethernity_version

DIRECTIONAL_WIDGET_ACTION_PREFIXES = ("cursor_",)
DIRECTIONAL_WIDGET_ACTIONS = {"next_choice", "previous_choice", "show_overlay"}
NAV_GROUPS: tuple[tuple[str, tuple[ActiveTask, ...]], ...] = tuple(
    (group, tuple(workflow.key for workflow in workflows_in_group(group)))
    for group in WORKFLOW_GROUPS
)
NAV_NUMBERS: dict[ActiveTask, str] = {
    workflow.key: workflow.shortcut
    for group in WORKFLOW_GROUPS
    for workflow in workflows_in_group(group)
}
NAV_LABELS: dict[ActiveTask, str] = {
    "backup": "Create backup",
    "restore": "Restore files",
    "add_files": "Add files",
    "rebuild": "Rebuild backup",
    "replace_recovery_docs": "Replacement sheets",
    "kit": "Recovery kit",
    "settings": "Settings",
}


def _is_directional_widget_action(action: str) -> bool:
    action_name = action.split("(", 1)[0]
    return action_name in DIRECTIONAL_WIDGET_ACTIONS or action_name.startswith(
        DIRECTIONAL_WIDGET_ACTION_PREFIXES
    )


async def run_directional_widget_binding(focused: Widget | None, key: str) -> bool:
    if focused is None:
        return False
    active_binding = focused.screen.active_bindings.get(key)
    if active_binding is None or not active_binding.enabled:
        return False
    action = active_binding.binding.action
    if not _is_directional_widget_action(action):
        return False
    return await focused.app.run_action(action, default_namespace=active_binding.node)


def nav_items(active_task: ActiveTask | None = None) -> tuple[ListItem, ...]:
    items: list[ListItem] = []
    for group_label, task_keys in NAV_GROUPS:
        items.append(_nav_header(group_label))
        items.extend(_nav_item(task_key, active_task) for task_key in task_keys)
    return tuple(items)


NavTaskState = Literal["", "in-progress", "ready", "attention"]


def sync_nav_active(
    nav: ListView,
    active_task: ActiveTask,
    task_states: Mapping[ActiveTask, NavTaskState] | None = None,
) -> None:
    for item in nav.query(ListItem):
        task_key = _nav_item_task(item)
        if task_key is None:
            continue
        active = task_key == active_task
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
    nav.index = NAV_OPTION_INDEX[active_task]


def workspace_focus_selector(task: ActiveTask) -> str:
    return workflow_definition(task).initial_focus


def blocker_focus_selector(task: ActiveTask, section: str | None) -> str:
    return workflow_definition(task).focus_for_section(section)


def issue_focus_selector(task: ActiveTask, issue: TaskIssue | None) -> str:
    if issue is None:
        return workspace_focus_selector(task)
    return workflow_definition(task).focus_for_issue(issue.code, issue.section)


def app_version_label() -> str:
    version = get_ethernity_version()
    return f"v{version}" if version else "dev"


def _nav_item_task(item: ListItem) -> ActiveTask | None:
    item_id = item.id
    if item_id in TASK_TITLES:
        return cast(ActiveTask, item_id)
    return None


def _nav_header(label: str) -> ListItem:
    return ListItem(
        Label(label.upper(), classes="nav-section-label"),
        disabled=True,
        classes="nav-section",
    )


def _nav_item(task_key: ActiveTask, active_task: ActiveTask | None) -> ListItem:
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
        classes="nav-workflow active" if active else "nav-workflow",
    )
