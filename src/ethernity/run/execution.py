from __future__ import annotations

import click

from ethernity.run.json_io import print_task_json
from ethernity.run.output import (
    print_task_execution_result,
    print_task_preview,
    print_task_validation,
)
from ethernity.tasks.models import (
    TaskExecutionPlan,
    TaskExecutionResult,
    TaskPreview,
    TaskState,
    TaskValidation,
)


def run_task(
    task_name: str,
    state: TaskState,
    *,
    preview: bool,
    yes: bool,
    json_output: bool,
    not_ready_message: str,
    execute_without_confirmation: bool = False,
) -> None:
    prepare_review = getattr(state, "prepare_review", None)
    if callable(prepare_review):
        prepare_review(force=True)
    validation = state.validate_task()
    task_preview = state.preview()
    plan = state.execution_plan()

    if json_output:
        _run_task_json(
            task_name,
            state,
            validation,
            task_preview,
            plan,
            preview_mode=preview,
            yes=yes,
            not_ready_message=not_ready_message,
            execute_without_confirmation=execute_without_confirmation,
        )
        return

    print_task_validation(validation)
    print_task_preview(task_preview)
    if preview:
        return
    if not validation.ready:
        raise click.ClickException(not_ready_message)
    if not yes and not execute_without_confirmation:
        raise click.ClickException("Use --preview to inspect the task or --yes to execute.")
    result = _execute_task(task_name, state, validation, task_preview, plan, json_output=False)
    print_task_execution_result(result)


def _run_task_json(
    task_name: str,
    state: TaskState,
    validation: TaskValidation,
    task_preview: TaskPreview,
    plan: TaskExecutionPlan,
    *,
    preview_mode: bool,
    yes: bool,
    not_ready_message: str,
    execute_without_confirmation: bool,
) -> None:
    if preview_mode:
        print_task_json(
            task=task_name,
            status="preview",
            validation=validation,
            preview=task_preview,
            plan=plan,
        )
        return
    if not validation.ready:
        print_task_json(
            task=task_name,
            status="not_ready",
            validation=validation,
            preview=task_preview,
            plan=plan,
            error=not_ready_message,
        )
        raise click.exceptions.Exit(1)
    if not yes and not execute_without_confirmation:
        error = "Use --preview to inspect the task or --yes to execute."
        print_task_json(
            task=task_name,
            status="confirmation_required",
            validation=validation,
            preview=task_preview,
            plan=plan,
            error=error,
        )
        raise click.exceptions.Exit(2)

    result = _execute_task(task_name, state, validation, task_preview, plan, json_output=True)
    print_task_json(
        task=task_name,
        status="executed",
        validation=validation,
        preview=task_preview,
        plan=plan,
        result=result,
    )


def _execute_task(
    task_name: str,
    state: TaskState,
    validation: TaskValidation,
    preview: TaskPreview,
    plan: TaskExecutionPlan,
    *,
    json_output: bool,
) -> TaskExecutionResult:
    try:
        return state.execute()
    except ValueError as exc:
        if json_output:
            print_task_json(
                task=task_name,
                status="error",
                validation=validation,
                preview=preview,
                plan=plan,
                error=str(exc),
            )
            raise click.exceptions.Exit(1) from exc
        raise click.ClickException(str(exc)) from exc
