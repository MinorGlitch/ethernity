from __future__ import annotations

from pathlib import Path

import click

from ethernity.run.context import current_config_path
from ethernity.run.execution import run_task
from ethernity.tasks.rebuild import RebuildTaskState


@click.command()
@click.option(
    "--backup-folder",
    type=click.Path(file_okay=False, path_type=Path),
    help="Generated backup folder to rebuild from.",
)
@click.option(
    "--scan",
    "source_paths",
    multiple=True,
    type=click.Path(exists=False, path_type=Path),
    help="Printed/scanned backup source. Repeat for multiple paths.",
)
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    help="Where rebuilt backup documents will be saved.",
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
@click.option("--qr-chunk-size", type=click.IntRange(min=1), help="Payload bytes per QR chunk.")
@click.option(
    "--expected-head",
    "expected_head_doc_hash",
    help="Expected latest backup fingerprint.",
)
@click.option("--allow-stale-head", is_flag=True, help="Accept scan source freshness risk.")
@click.option("--paper", "paper_size", type=click.Choice(["A4", "LETTER"]), default="A4")
@click.option("--design", default="sentinel", show_default=True, help="Built-in render style.")
@click.option("--preview", is_flag=True, help="Preview the task without writing files.")
@click.option("--yes", is_flag=True, help="Run without interactive confirmation.")
@click.option("--json", "json_output", is_flag=True, help="Emit one machine-readable JSON object.")
@click.pass_context
def rebuild(
    ctx: click.Context,
    backup_folder: Path | None,
    source_paths: tuple[Path, ...],
    output_dir: Path | None,
    passphrase: str | None,
    recovery_documents: tuple[Path, ...],
    recovery_payload_files: tuple[Path, ...],
    auth_text_file: Path | None,
    auth_payloads_file: Path | None,
    qr_chunk_size: int | None,
    expected_head_doc_hash: str | None,
    allow_stale_head: bool,
    paper_size: str,
    design: str,
    preview: bool,
    yes: bool,
    json_output: bool,
) -> None:
    """Rebuild a backup from its latest recoverable state."""

    state = RebuildTaskState(
        backup_folder=backup_folder,
        config_path=current_config_path(ctx),
        source_paths=list(source_paths),
        output_dir=output_dir,
        passphrase=passphrase,
        recovery_documents=list(recovery_documents),
        recovery_payload_files=list(recovery_payload_files),
        auth_text_file=auth_text_file,
        auth_payloads_file=auth_payloads_file,
        qr_chunk_size=qr_chunk_size,
        expected_head_doc_hash=expected_head_doc_hash,
        allow_stale_head=allow_stale_head,
        paper_size=paper_size,
        design=design,
    )
    run_task(
        "rebuild",
        state,
        preview=preview,
        yes=yes,
        json_output=json_output,
        not_ready_message="Rebuild is not ready.",
    )


__all__ = ["rebuild"]
