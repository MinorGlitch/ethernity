from __future__ import annotations

from pathlib import Path

import click

from ethernity.page_sizes import DEFAULT_PAPER_SIZE_NAME, paper_size_names, resolve_paper_size
from ethernity.run.context import current_config_path
from ethernity.run.execution import run_task
from ethernity.tasks.quorum import MAX_SHARDS
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState


@click.command("replace-recovery-docs")
@click.option(
    "--scan",
    "source_paths",
    multiple=True,
    type=click.Path(exists=False, path_type=Path),
    help="Printed/scanned backup source. Repeat for multiple paths.",
)
@click.option(
    "--recovery-text",
    "recovery_text_file",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Recovery text file for the existing backup.",
)
@click.option(
    "--payloads-file",
    type=click.Path(dir_okay=False, path_type=Path),
    help="File containing existing backup QR payloads.",
)
@click.option("--passphrase", help="Passphrase to unlock the backup.")
@click.option(
    "--recovery-document",
    "recovery_documents",
    multiple=True,
    type=click.Path(exists=False, path_type=Path),
    help="Existing recovery document path. Repeat for multiple documents.",
)
@click.option(
    "--recovery-payloads-file",
    "recovery_payload_files",
    multiple=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="File containing existing recovery document payloads. Repeat for multiple files.",
)
@click.option(
    "--signing-key-payloads-file",
    "signing_key_recovery_payload_files",
    multiple=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="File containing signing-key recovery payloads. Repeat for multiple files.",
)
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    help="Where replacement recovery documents will be saved.",
)
@click.option(
    "--expected-head",
    "expected_head_doc_hash",
    help="Expected latest backup fingerprint.",
)
@click.option("--allow-stale-head", is_flag=True, help="Accept scan source freshness risk.")
@click.option(
    "--recovery-threshold",
    type=click.IntRange(min=1, max=MAX_SHARDS),
    default=2,
    show_default=True,
    help="How many replacement recovery documents will be needed.",
)
@click.option(
    "--recovery-count",
    "recovery_document_count",
    type=click.IntRange(min=1, max=MAX_SHARDS),
    default=3,
    show_default=True,
    help="How many replacement recovery documents to create.",
)
@click.option(
    "--passphrase-recovery/--no-passphrase-recovery",
    "mint_passphrase_recovery",
    default=True,
    help="Create replacement passphrase recovery documents.",
)
@click.option(
    "--signing-key-recovery",
    "mint_signing_key_recovery",
    is_flag=True,
    help="Create replacement signing-key recovery documents.",
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
@click.option(
    "--passphrase-replacement-count",
    type=click.IntRange(min=1),
    help="How many passphrase recovery documents to replace.",
)
@click.option(
    "--signing-key-replacement-count",
    type=click.IntRange(min=1),
    help="How many signing-key recovery documents to replace.",
)
@click.option(
    "--paper",
    "paper_size",
    type=click.Choice(paper_size_names()),
    default=DEFAULT_PAPER_SIZE_NAME,
)
@click.option("--design", default="sentinel", show_default=True, help="Built-in render style.")
@click.option("--preview", is_flag=True, help="Preview the task without writing files.")
@click.option("--yes", is_flag=True, help="Run without interactive confirmation.")
@click.option("--json", "json_output", is_flag=True, help="Emit one machine-readable JSON object.")
@click.pass_context
def replace_recovery_docs(
    ctx: click.Context,
    source_paths: tuple[Path, ...],
    recovery_text_file: Path | None,
    payloads_file: Path | None,
    passphrase: str | None,
    recovery_documents: tuple[Path, ...],
    recovery_payload_files: tuple[Path, ...],
    signing_key_recovery_payload_files: tuple[Path, ...],
    output_dir: Path | None,
    expected_head_doc_hash: str | None,
    allow_stale_head: bool,
    recovery_threshold: int,
    recovery_document_count: int,
    mint_passphrase_recovery: bool,
    mint_signing_key_recovery: bool,
    signing_key_recovery_threshold: int | None,
    signing_key_recovery_count: int | None,
    passphrase_replacement_count: int | None,
    signing_key_replacement_count: int | None,
    paper_size: str,
    design: str,
    preview: bool,
    yes: bool,
    json_output: bool,
) -> None:
    """Create replacement recovery documents for an existing backup."""

    state = ReplaceRecoveryDocsTaskState(
        source_paths=list(source_paths),
        recovery_text_file=recovery_text_file,
        payloads_file=payloads_file,
        config_path=current_config_path(ctx),
        passphrase=passphrase,
        recovery_documents=list(recovery_documents),
        recovery_payload_files=list(recovery_payload_files),
        signing_key_recovery_payload_files=list(signing_key_recovery_payload_files),
        output_dir=output_dir,
        expected_head_doc_hash=expected_head_doc_hash,
        allow_stale_head=allow_stale_head,
        recovery_threshold=recovery_threshold,
        recovery_document_count=recovery_document_count,
        mint_passphrase_recovery=mint_passphrase_recovery,
        mint_signing_key_recovery=mint_signing_key_recovery,
        signing_key_recovery_threshold=signing_key_recovery_threshold,
        signing_key_recovery_count=signing_key_recovery_count,
        passphrase_replacement_count=passphrase_replacement_count,
        signing_key_replacement_count=signing_key_replacement_count,
        paper_size=resolve_paper_size(paper_size).name,
        design=design,
    )
    run_task(
        "replace-recovery-docs",
        state,
        preview=preview,
        yes=yes,
        json_output=json_output,
        not_ready_message="Replace recovery documents is not ready.",
    )


__all__ = ["replace_recovery_docs"]
