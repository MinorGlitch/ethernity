from __future__ import annotations

from pathlib import Path
from typing import cast

import click

from ethernity.run.context import current_config_path
from ethernity.run.execution import run_task
from ethernity.tasks.add_files import (
    AddFilesSigningKeyMode,
    AddFilesTaskState,
    AddFilesUnlockPolicy,
)
from ethernity.tasks.quorum import MAX_SHARDS


@click.command("add-files")
@click.option(
    "--backup-folder",
    type=click.Path(file_okay=False, path_type=Path),
    help="Generated backup folder to update.",
)
@click.option(
    "--scan",
    "source_paths",
    multiple=True,
    type=click.Path(exists=False, path_type=Path),
    help="Printed/scanned current backup source. Repeat for multiple paths.",
)
@click.option(
    "--input",
    "input_paths",
    multiple=True,
    type=click.Path(exists=False, path_type=Path),
    help="File to add. Repeat for multiple files.",
)
@click.option(
    "--input-dir",
    "input_dirs",
    multiple=True,
    type=click.Path(file_okay=False, exists=False, path_type=Path),
    help="Folder to add. Repeat for multiple folders.",
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
@click.option("--allow-stale-head", is_flag=True, help="Accept scan source freshness risk.")
@click.option(
    "--recovery-count",
    "recovery_document_count",
    type=click.IntRange(min=0, max=MAX_SHARDS),
    help="How many new recovery documents to create.",
)
@click.option(
    "--recovery-threshold",
    "recovery_document_threshold",
    type=click.IntRange(min=1, max=MAX_SHARDS),
    help="How many new recovery documents will be needed.",
)
@click.option(
    "--unlock-policy",
    type=click.Choice(["self-contained", "reuse-root"]),
    default="self-contained",
    show_default=True,
    help="How the update should store unlock material.",
)
@click.option(
    "--signing-key-mode",
    type=click.Choice(["not-stored", "sharded"]),
    help="How the update signing key is stored.",
)
@click.option(
    "--signing-key-threshold",
    "signing_key_recovery_threshold",
    type=click.IntRange(min=1, max=MAX_SHARDS),
    help="How many signing-key recovery documents will be needed.",
)
@click.option(
    "--signing-key-count",
    "signing_key_recovery_count",
    type=click.IntRange(min=1, max=MAX_SHARDS),
    help="How many signing-key recovery documents to create.",
)
@click.option("--qr-chunk-size", type=click.IntRange(min=1), help="Payload bytes per QR chunk.")
@click.option("--paper", "paper_size", type=click.Choice(["A4", "LETTER"]), default="A4")
@click.option("--design", default="sentinel", show_default=True, help="Built-in render style.")
@click.option("--preview", is_flag=True, help="Preview the task without writing files.")
@click.option("--yes", is_flag=True, help="Run without interactive confirmation.")
@click.option("--json", "json_output", is_flag=True, help="Emit one machine-readable JSON object.")
@click.pass_context
def add_files(
    ctx: click.Context,
    backup_folder: Path | None,
    source_paths: tuple[Path, ...],
    input_paths: tuple[Path, ...],
    input_dirs: tuple[Path, ...],
    base_dir: Path | None,
    passphrase: str | None,
    recovery_documents: tuple[Path, ...],
    recovery_payload_files: tuple[Path, ...],
    expected_head_doc_hash: str | None,
    allow_stale_head: bool,
    recovery_document_count: int | None,
    recovery_document_threshold: int | None,
    unlock_policy: str,
    signing_key_mode: str | None,
    signing_key_recovery_threshold: int | None,
    signing_key_recovery_count: int | None,
    qr_chunk_size: int | None,
    paper_size: str,
    design: str,
    preview: bool,
    yes: bool,
    json_output: bool,
) -> None:
    """Add files to an existing backup."""

    state = AddFilesTaskState(
        backup_folder=backup_folder,
        config_path=current_config_path(ctx),
        source_paths=list(source_paths),
        input_paths=list(input_paths),
        input_dirs=list(input_dirs),
        base_dir=base_dir,
        passphrase=passphrase,
        recovery_documents=list(recovery_documents),
        recovery_payload_files=list(recovery_payload_files),
        expected_head_doc_hash=expected_head_doc_hash,
        allow_stale_head=allow_stale_head,
        unlock_policy=cast(AddFilesUnlockPolicy, unlock_policy),
        recovery_document_threshold=recovery_document_threshold,
        recovery_document_count=recovery_document_count,
        signing_key_mode=cast(AddFilesSigningKeyMode | None, signing_key_mode),
        signing_key_recovery_threshold=signing_key_recovery_threshold,
        signing_key_recovery_count=signing_key_recovery_count,
        qr_chunk_size=qr_chunk_size,
        paper_size=paper_size,
        design=design,
    )
    run_task(
        "add-files",
        state,
        preview=preview,
        yes=yes,
        json_output=json_output,
        not_ready_message="Add-files is not ready.",
    )


__all__ = ["add_files"]
