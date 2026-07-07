#!/usr/bin/env python3
# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

import json

import click

from ethernity.tasks.models import (
    TaskExecutionPlan,
    TaskExecutionResult,
    TaskPreview,
    TaskValidation,
)


def print_task_json(
    *,
    task: str,
    status: str,
    validation: TaskValidation,
    preview: TaskPreview,
    plan: TaskExecutionPlan,
    result: TaskExecutionResult | None = None,
    error: str | None = None,
) -> None:
    payload = {
        "task": task,
        "status": status,
        "ready": validation.ready,
        "validation": validation.model_dump(mode="json"),
        "preview": preview.model_dump(mode="json"),
        "plan": plan.model_dump(mode="json"),
        "result": result.model_dump(mode="json") if result is not None else None,
        "error": error,
    }
    click.echo(json.dumps(payload, sort_keys=True, separators=(",", ":")))
