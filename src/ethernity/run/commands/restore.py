from __future__ import annotations

from pathlib import Path

import click

from ethernity.run.context import current_config_path
from ethernity.run.execution import run_task
from ethernity.tasks.restore import RestoreTarget, RestoreTaskState


@click.command()
@click.option(
    "--scan",
    "source_paths",
    multiple=True,
    type=click.Path(exists=False, path_type=Path),
    help="PDF, image, or folder containing backup scans.",
)
@click.option(
    "--recovery-text",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Recovery text file.",
)
@click.option("--passphrase", help="Passphrase to unlock the backup.")
@click.option(
    "--recovery-document",
    "recovery_documents",
    multiple=True,
    type=click.Path(exists=False, path_type=Path),
    help="Printed recovery document path. Repeat for multiple documents.",
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
    "--recovery-payloads-file",
    "recovery_payload_files",
    multiple=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="File containing recovery document payloads. Repeat for multiple files.",
)
@click.option("--extension-index", type=click.IntRange(min=0), help="Restore one backup update.")
@click.option("--extension-doc-hash", help="Restore the backup update with this fingerprint.")
@click.option(
    "--expected-head",
    "expected_head_doc_hash",
    help="Expected latest backup fingerprint.",
)
@click.option("--allow-unsigned", is_flag=True, help="Allow unsigned legacy recovery payloads.")
@click.option(
    "--output",
    "output_path",
    type=click.Path(path_type=Path),
    help="Where recovered files will be written.",
)
@click.option("--preview", is_flag=True, help="Preview the task without writing files.")
@click.option("--yes", is_flag=True, help="Run without interactive confirmation.")
@click.option("--json", "json_output", is_flag=True, help="Emit one machine-readable JSON object.")
@click.pass_context
def restore(
    ctx: click.Context,
    source_paths: tuple[Path, ...],
    recovery_text: Path | None,
    passphrase: str | None,
    recovery_documents: tuple[Path, ...],
    payloads_file: Path | None,
    auth_text_file: Path | None,
    auth_payloads_file: Path | None,
    recovery_payload_files: tuple[Path, ...],
    extension_index: int | None,
    extension_doc_hash: str | None,
    expected_head_doc_hash: str | None,
    allow_unsigned: bool,
    output_path: Path | None,
    preview: bool,
    yes: bool,
    json_output: bool,
) -> None:
    """Restore files."""

    state = RestoreTaskState(
        source_paths=list(source_paths),
        recovery_text_file=recovery_text,
        payloads_file=payloads_file,
        auth_text_file=auth_text_file,
        auth_payloads_file=auth_payloads_file,
        config_path=current_config_path(ctx),
        passphrase=passphrase,
        recovery_documents=list(recovery_documents),
        recovery_payload_files=list(recovery_payload_files),
        target=_restore_target(extension_index, extension_doc_hash),
        extension_index=extension_index,
        extension_doc_hash=extension_doc_hash,
        expected_head_doc_hash=expected_head_doc_hash,
        output_path=output_path,
        allow_unsigned=allow_unsigned,
    )
    run_task(
        "restore",
        state,
        preview=preview,
        yes=yes,
        json_output=json_output,
        not_ready_message="Restore is not ready.",
    )


def _restore_target(
    extension_index: int | None,
    extension_doc_hash: str | None,
) -> RestoreTarget:
    if extension_index == 0:
        return "original"
    if extension_index is not None or extension_doc_hash is not None:
        return "specific_update"
    return "latest"


__all__ = ["restore"]
