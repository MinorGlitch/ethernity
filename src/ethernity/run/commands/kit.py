from __future__ import annotations

from pathlib import Path
from typing import cast

import click

from ethernity.run.execution import run_task
from ethernity.tasks.kit import KitVariant, PaperSize, PrintKitTaskState


@click.command("print-kit")
@click.option(
    "--output",
    "output_path",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Output PDF path.",
)
@click.option(
    "--variant",
    type=click.Choice(["lean", "scanner"]),
    default="lean",
    show_default=True,
    help="Recovery kit variant.",
)
@click.option("--paper", "paper_size", type=click.Choice(["A4", "LETTER"]), default="A4")
@click.option("--design", default="sentinel", show_default=True, help="Built-in render style.")
@click.option(
    "--qr-chunk-size",
    "chunk_size",
    type=click.IntRange(min=1),
    help="Payload bytes per QR chunk.",
)
@click.option("--preview", is_flag=True, help="Preview the task without writing files.")
@click.option("--yes", is_flag=True, help="Run without interactive confirmation.")
@click.option("--json", "json_output", is_flag=True, help="Emit one machine-readable JSON object.")
def print_kit(
    output_path: Path | None,
    variant: str,
    paper_size: str,
    design: str,
    chunk_size: int | None,
    preview: bool,
    yes: bool,
    json_output: bool,
) -> None:
    """Create a printable recovery kit PDF."""

    state = PrintKitTaskState(
        output_path=output_path or PrintKitTaskState().output_path,
        variant=cast(KitVariant, variant),
        paper_size=cast(PaperSize, paper_size),
        design=design,
        chunk_size=chunk_size,
    )
    run_task(
        "print-kit",
        state,
        preview=preview,
        yes=yes,
        json_output=json_output,
        not_ready_message="Recovery kit is not ready.",
    )


__all__ = ["print_kit"]
