from __future__ import annotations

from pathlib import Path
from typing import cast

import click

from ethernity.crypto import MNEMONIC_WORD_COUNTS
from ethernity.run.context import current_config_path
from ethernity.run.execution import run_task
from ethernity.tasks.backup import BackupTaskState, PaperSize, SigningKeyMode
from ethernity.tasks.quorum import MAX_SHARDS

PASSPHRASE_WORD_CHOICES = tuple(str(count) for count in MNEMONIC_WORD_COUNTS)


@click.command()
@click.option(
    "--input",
    "input_paths",
    multiple=True,
    type=click.Path(exists=False, path_type=Path),
    help="File or folder to include. Repeat for multiple paths.",
)
@click.option(
    "--input-dir",
    "input_dirs",
    multiple=True,
    type=click.Path(file_okay=False, exists=False, path_type=Path),
    help="Folder to include. Repeat for multiple folders.",
)
@click.option(
    "--base-dir",
    type=click.Path(file_okay=False, path_type=Path),
    help="Base folder used for relative paths in the backup.",
)
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    help="Where backup documents will be saved.",
)
@click.option(
    "--recovery-threshold",
    type=click.IntRange(min=1, max=MAX_SHARDS),
    default=2,
    show_default=True,
    help="How many recovery documents will be needed.",
)
@click.option(
    "--recovery-count",
    type=click.IntRange(min=0, max=MAX_SHARDS),
    default=3,
    show_default=True,
    help="How many recovery documents to create. Use 0 for passphrase-only recovery.",
)
@click.option(
    "--signing-key-mode",
    type=click.Choice(["embedded", "sharded"]),
    default="embedded",
    show_default=True,
    help="How the backup signing key is stored.",
)
@click.option(
    "--signing-key-threshold",
    "signing_key_shard_threshold",
    type=click.IntRange(min=1, max=MAX_SHARDS),
    help="How many signing-key recovery documents will be needed.",
)
@click.option(
    "--signing-key-count",
    "signing_key_shard_count",
    type=click.IntRange(min=1, max=MAX_SHARDS),
    help="How many signing-key recovery documents to create.",
)
@click.option("--qr-chunk-size", type=click.IntRange(min=1), help="Payload bytes per QR chunk.")
@click.option("--paper", "paper_size", type=click.Choice(["A4", "LETTER"]), default="A4")
@click.option("--design", default="sentinel", show_default=True, help="Built-in render style.")
@click.option("--preview", is_flag=True, help="Preview the task without writing files.")
@click.option("--yes", is_flag=True, help="Run without interactive confirmation.")
@click.option("--passphrase", help="Use this passphrase. Omit to generate one.")
@click.option(
    "--passphrase-words",
    type=click.Choice(PASSPHRASE_WORD_CHOICES),
    help="Generated passphrase word count.",
)
@click.option("--json", "json_output", is_flag=True, help="Emit one machine-readable JSON object.")
@click.pass_context
def backup(
    ctx: click.Context,
    input_paths: tuple[Path, ...],
    input_dirs: tuple[Path, ...],
    base_dir: Path | None,
    output_dir: Path | None,
    recovery_threshold: int,
    recovery_count: int,
    signing_key_mode: str,
    signing_key_shard_threshold: int | None,
    signing_key_shard_count: int | None,
    qr_chunk_size: int | None,
    paper_size: str,
    design: str,
    preview: bool,
    yes: bool,
    passphrase: str | None,
    passphrase_words: str | None,
    json_output: bool,
) -> None:
    """Create a backup."""

    generated_words = int(passphrase_words) if passphrase_words is not None else None
    state = BackupTaskState(
        input_paths=list(input_paths),
        input_dirs=list(input_dirs),
        base_dir=base_dir,
        config_path=current_config_path(ctx),
        output_dir=output_dir,
        recovery_method="single_phrase" if recovery_count == 0 else "custom_shards",
        shard_threshold=recovery_threshold,
        shard_count=recovery_count,
        passphrase=passphrase,
        passphrase_words=generated_words,
        paper_size=cast(PaperSize, paper_size),
        design=design,
        signing_key_mode=cast(SigningKeyMode, signing_key_mode),
        signing_key_shard_threshold=signing_key_shard_threshold,
        signing_key_shard_count=signing_key_shard_count,
        qr_chunk_size=qr_chunk_size,
    )
    run_task(
        "backup",
        state,
        preview=preview,
        yes=yes,
        json_output=json_output,
        not_ready_message="Backup is not ready.",
    )


__all__ = ["backup"]
