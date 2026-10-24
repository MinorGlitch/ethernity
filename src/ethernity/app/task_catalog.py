from __future__ import annotations

from ethernity.app.workflow_registry import WORKFLOWS, workflow_definition
from ethernity.tasks.task_types import TaskKey

TASK_TITLES: dict[TaskKey, str] = {workflow.key: workflow.title for workflow in WORKFLOWS}

TASK_ORDER: tuple[TaskKey, ...] = tuple(workflow.key for workflow in WORKFLOWS)


def execute_label(task: TaskKey) -> str:
    return workflow_definition(task).execute_label


def review_label(task: TaskKey) -> str:
    return workflow_definition(task).review_label
