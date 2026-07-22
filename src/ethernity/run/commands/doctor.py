from __future__ import annotations

from pathlib import Path

import click

from ethernity.run.execution import run_task
from ethernity.tasks.doctor import DoctorTaskState


@click.command()
@click.option(
    "--backup-folder",
    type=click.Path(file_okay=False, path_type=Path),
    required=True,
    help="Canonical generated backup folder containing publication transactions.",
)
@click.option("--passphrase", required=True, help="Passphrase used to authenticate the chain.")
@click.option(
    "--repair",
    is_flag=True,
    help="Clean up committed duplicates or quarantine authenticated unpublished transactions.",
)
@click.option("--yes", is_flag=True, help="Confirm repair operations.")
@click.option("--json", "json_output", is_flag=True, help="Emit one machine-readable JSON object.")
def doctor(
    backup_folder: Path,
    passphrase: str,
    repair: bool,
    yes: bool,
    json_output: bool,
) -> None:
    """Inspect or repair interrupted publication transactions."""

    state = DoctorTaskState(
        backup_folder=backup_folder,
        passphrase=passphrase,
        repair=repair,
    )
    run_task(
        "doctor",
        state,
        preview=False,
        yes=yes,
        json_output=json_output,
        not_ready_message="Doctor operation is not ready.",
        execute_without_confirmation=not repair,
    )


__all__ = ["doctor"]
