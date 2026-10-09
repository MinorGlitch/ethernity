from __future__ import annotations

from pathlib import Path
from typing import cast

import click

from ethernity.page_sizes import DEFAULT_PAPER_SIZE_NAME, paper_size_names, resolve_paper_size
from ethernity.run.execution import run_task
from ethernity.tasks.kit import KitVariant, PrintKitTaskState


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
    help="Offline recovery kit variant.",
)
@click.option(
    "--paper",
    "paper_size",
    type=click.Choice(paper_size_names()),
    default=DEFAULT_PAPER_SIZE_NAME,
)
@click.option("--design", default="sentinel", show_default=True, help="Built-in render style.")
@click.option(
    "--qr-chunk-size",
    "chunk_size",
    type=click.IntRange(min=1),
    help="Payload bytes per QR chunk.",
)
@click.option("--preview", is_flag=True, help="Preview the task without writing files.")
@click.option("--yes", is_flag=True, help="Run without interactive confirmation.")
def print_kit(
    output_path: Path | None,
    variant: str,
    paper_size: str,
    design: str,
    chunk_size: int | None,
    preview: bool,
    yes: bool,
) -> None:
    """Create a printable offline recovery kit PDF."""

    state = PrintKitTaskState(
        output_path=output_path or PrintKitTaskState().output_path,
        variant=cast(KitVariant, variant),
        paper_size=resolve_paper_size(paper_size).name,
        design=design,
        chunk_size=chunk_size,
    )
    run_task(
        state,
        not_ready_message="Offline recovery kit is not ready.",
        preview=preview,
        yes=yes,
    )


__all__ = ["print_kit"]
