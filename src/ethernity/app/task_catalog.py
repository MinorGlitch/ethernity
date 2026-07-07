from __future__ import annotations

from ethernity.app.app_types import ActiveTask

TASK_TITLES: dict[ActiveTask, str] = {
    "backup": "Create backup",
    "restore": "Restore files",
    "add_files": "Add files to backup",
    "rebuild": "Rebuild backup",
    "replace_recovery_docs": "Create replacement recovery sheets",
    "kit": "Create recovery kit PDF",
    "doctor": "Setup check",
    "settings": "Settings",
}

TASK_ORDER: tuple[ActiveTask, ...] = (
    "backup",
    "restore",
    "add_files",
    "rebuild",
    "replace_recovery_docs",
    "kit",
    "doctor",
    "settings",
)

NAV_OPTION_INDEX: dict[ActiveTask, int] = {
    "backup": 1,
    "restore": 3,
    "add_files": 5,
    "rebuild": 6,
    "replace_recovery_docs": 7,
    "kit": 9,
    "doctor": 10,
    "settings": 11,
}


def execute_label(task: ActiveTask) -> str:
    if task == "restore":
        return "Restore files"
    if task == "add_files":
        return "Create update"
    if task == "rebuild":
        return "Rebuild backup"
    if task == "replace_recovery_docs":
        return "Create replacement sheets"
    if task == "kit":
        return "Create PDF"
    if task == "doctor":
        return "Run checks again"
    if task == "settings":
        return "Save settings"
    return "Create backup"


def review_label(task: ActiveTask) -> str:
    if task == "restore":
        return "Review restore"
    if task == "add_files":
        return "Review update"
    if task == "rebuild":
        return "Review rebuild"
    if task == "replace_recovery_docs":
        return "Review replacement sheets"
    if task == "kit":
        return "Review PDF"
    if task == "doctor":
        return "Run checks again"
    if task == "settings":
        return "Save"
    return "Review backup"
