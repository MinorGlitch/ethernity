from __future__ import annotations

from ethernity.app.app_types import ActiveTask
from ethernity.app.workflow_registry import WORKFLOWS, nav_option_indices, workflow_definition

TASK_TITLES: dict[ActiveTask, str] = {workflow.key: workflow.title for workflow in WORKFLOWS}

TASK_ORDER: tuple[ActiveTask, ...] = tuple(workflow.key for workflow in WORKFLOWS)

NAV_OPTION_INDEX: dict[ActiveTask, int] = nav_option_indices()


def execute_label(task: ActiveTask) -> str:
    return workflow_definition(task).execute_label


def review_label(task: ActiveTask) -> str:
    return workflow_definition(task).review_label
