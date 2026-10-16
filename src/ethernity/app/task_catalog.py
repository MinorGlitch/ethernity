from __future__ import annotations

from ethernity.app.workflow_registry import WORKFLOWS, nav_option_indices, workflow_definition
from ethernity.tasks.task_types import TaskKey

TASK_TITLES: dict[TaskKey, str] = {workflow.key: workflow.title for workflow in WORKFLOWS}

TASK_ORDER: tuple[TaskKey, ...] = tuple(workflow.key for workflow in WORKFLOWS)

NAV_OPTION_INDEX: dict[TaskKey, int] = nav_option_indices()


def execute_label(task: TaskKey) -> str:
    return workflow_definition(task).execute_label


def review_label(task: TaskKey) -> str:
    return workflow_definition(task).review_label
