from __future__ import annotations

import click

from ethernity.run.execution import run_task
from ethernity.tasks.doctor import DoctorTaskState


@click.command()
@click.option("--json", "json_output", is_flag=True, help="Emit one machine-readable JSON object.")
def doctor(json_output: bool) -> None:
    """Check the local Ethernity setup."""

    run_task(
        "doctor",
        DoctorTaskState(),
        preview=False,
        yes=True,
        json_output=json_output,
        not_ready_message="Setup check is not ready.",
        execute_without_confirmation=True,
    )


__all__ = ["doctor"]
