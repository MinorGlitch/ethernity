from __future__ import annotations

from pathlib import Path

import click

from ethernity.crypto.sharding import MAX_SHARES
from ethernity.page_sizes import paper_size_names, resolve_paper_size
from ethernity.run.context import current_config_path
from ethernity.run.execution import run_task
from ethernity.tasks.add_files import AddFilesTaskState


@click.command("add-files")
@click.option(
    "--scan",
    "source_paths",
    multiple=True,
    type=click.Path(exists=False, path_type=Path),
    help="Backup PDF, image, or folder of documents. Repeat for multiple inputs.",
)
@click.option(
    "--recovery-text",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Recovery text file containing the backup documents.",
)
@click.option(
    "--payloads-file",
    type=click.Path(dir_okay=False, path_type=Path),
    help="File containing backup QR payloads.",
)
@click.option(
    "--auth-text",
    "--auth-fallback-file",
    "auth_text_file",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Authentication recovery text file.",
)
@click.option(
    "--auth-payloads-file",
    type=click.Path(dir_okay=False, path_type=Path),
    help="File containing authentication payloads.",
)
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    help="New folder for the update documents.",
)
@click.option(
    "--input",
    "input_paths",
    multiple=True,
    type=click.Path(exists=False, path_type=Path),
    help="File to add or replace. Repeat for multiple files.",
)
@click.option(
    "--input-dir",
    "input_dirs",
    multiple=True,
    type=click.Path(file_okay=False, exists=False, path_type=Path),
    help="Folder to add or replace. Repeat for multiple folders.",
)
@click.option(
    "--base-dir",
    type=click.Path(file_okay=False, path_type=Path),
    help="Base folder used for relative paths in the update.",
)
@click.option("--passphrase", help="Passphrase to unlock the backup.")
@click.option(
    "--recovery-document",
    "recovery_documents",
    multiple=True,
    type=click.Path(exists=False, path_type=Path),
    help="Recovery document path. Repeat for multiple documents.",
)
@click.option(
    "--recovery-payloads-file",
    "recovery_payload_files",
    multiple=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="File containing recovery document payloads. Repeat for multiple files.",
)
@click.option(
    "--expected-head",
    "expected_head_doc_hash",
    help="Expected latest backup fingerprint.",
)
@click.option(
    "--allow-stale-head",
    is_flag=True,
    help="Accept that the loaded documents may omit a newer version.",
)
@click.option(
    "--new-recovery-sheets/--no-new-recovery-sheets",
    "create_recovery_sheets",
    default=False,
    help="After publishing, create passphrase recovery sheets bound to the root backup.",
)
@click.option(
    "--recovery-threshold",
    type=click.IntRange(min=1, max=MAX_SHARES),
    default=2,
    show_default=True,
    help="How many of the new recovery sheets will be needed.",
)
@click.option(
    "--recovery-count",
    "recovery_sheet_count",
    type=click.IntRange(min=1, max=MAX_SHARES),
    default=3,
    show_default=True,
    help="How many new recovery sheets to create.",
)
@click.option("--qr-chunk-size", type=click.IntRange(min=1), help="Payload bytes per QR chunk.")
@click.option("--paper", "paper_size", type=click.Choice(paper_size_names()))
@click.option("--design", help="Built-in render style; otherwise use the saved style.")
@click.option("--preview", is_flag=True, help="Preview the task without writing files.")
@click.option("--yes", is_flag=True, help="Run without interactive confirmation.")
@click.option("--json", "json_output", is_flag=True, help="Emit one machine-readable JSON object.")
@click.pass_context
def add_files(
    ctx: click.Context,
    source_paths: tuple[Path, ...],
    recovery_text: Path | None,
    payloads_file: Path | None,
    auth_text_file: Path | None,
    auth_payloads_file: Path | None,
    output_dir: Path | None,
    input_paths: tuple[Path, ...],
    input_dirs: tuple[Path, ...],
    base_dir: Path | None,
    passphrase: str | None,
    recovery_documents: tuple[Path, ...],
    recovery_payload_files: tuple[Path, ...],
    expected_head_doc_hash: str | None,
    allow_stale_head: bool,
    create_recovery_sheets: bool,
    recovery_threshold: int,
    recovery_sheet_count: int,
    qr_chunk_size: int | None,
    paper_size: str | None,
    design: str | None,
    preview: bool,
    yes: bool,
    json_output: bool,
) -> None:
    """Add or replace files in an existing backup."""

    state = AddFilesTaskState(
        source_paths=list(source_paths),
        recovery_text_file=recovery_text,
        payloads_file=payloads_file,
        auth_text_file=auth_text_file,
        auth_payloads_file=auth_payloads_file,
        output_dir=output_dir,
        config_path=current_config_path(ctx),
        input_paths=list(input_paths),
        input_dirs=list(input_dirs),
        base_dir=base_dir,
        passphrase=passphrase,
        recovery_documents=list(recovery_documents),
        recovery_payload_files=list(recovery_payload_files),
        expected_head_doc_hash=expected_head_doc_hash,
        allow_stale_head=allow_stale_head,
        create_recovery_sheets=create_recovery_sheets,
        recovery_threshold=recovery_threshold,
        recovery_sheet_count=recovery_sheet_count,
        qr_chunk_size=qr_chunk_size,
        paper_size=(resolve_paper_size(paper_size).name if paper_size is not None else None),
        design=design,
    )
    run_task(
        "add-files",
        state,
        preview=preview,
        yes=yes,
        json_output=json_output,
        not_ready_message="Add Files is not ready.",
    )


__all__ = ["add_files"]
