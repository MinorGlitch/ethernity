from __future__ import annotations

import click

from ethernity.crypto.age_runtime import AgeError
from ethernity.qr.scan import QrScanError
from ethernity.run.output import (
    print_task_execution_result,
    print_task_preview,
    print_task_validation,
)
from ethernity.security.resource_worker import DisposableWorkerError
from ethernity.tasks.models import TaskState
from ethernity.workflows.add_files.errors import AddFilesWorkflowError
from ethernity.workflows.execution import WorkflowExecutionError


def run_task(
    state: TaskState,
    *,
    not_ready_message: str,
    preview: bool,
    yes: bool,
) -> None:
    try:
        prepare_review = getattr(state, "prepare_review", None)
        if callable(prepare_review):
            prepare_review(force=True)
        validation = state.validate_task()
        task_preview = state.preview()

        print_task_validation(validation)
        print_task_preview(task_preview)
        if preview:
            return
        if not validation.ready:
            raise click.ClickException(not_ready_message)
        if not yes:
            raise click.ClickException("Use --preview to inspect the task or --yes to execute.")
        result = state.execute()
    except (
        ValueError,
        OSError,
        WorkflowExecutionError,
        AddFilesWorkflowError,
        AgeError,
        QrScanError,
        DisposableWorkerError,
    ) as exc:
        raise click.ClickException(str(exc)) from exc
    print_task_execution_result(result)
