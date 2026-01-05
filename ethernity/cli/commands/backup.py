#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import typer

from ..core.common import _ctx_value, _resolve_config_and_paper, _run_cli
from ..flows.backup import _should_use_wizard_for_backup, run_backup_command, run_wizard
from ..ui import DEBUG_MAX_BYTES_DEFAULT, console_err


def register(app: typer.Typer) -> None:
    @app.command(
        help=(
            "Create a backup PDF.\n\n"
            "Examples:\n"
            "  ethernity backup -i secrets.txt\n"
            "  ethernity backup --input-dir docs --output-dir backups\n"
            "  ethernity backup --mode recipient --recipient age1...\n"
        )
    )
    def backup(
        ctx: typer.Context,
        input: list[Path] = typer.Option(
            None,
            "--input",
            "-i",
            help="File to include (repeatable, use - for stdin).",
            rich_help_panel="Inputs",
        ),
        input_dir: list[Path] = typer.Option(
            None,
            "--input-dir",
            help="Folder to include (recursive, repeatable).",
            rich_help_panel="Inputs",
        ),
        base_dir: str | None = typer.Option(
            None,
            "--base-dir",
            help="Base path for stored relative names.",
            rich_help_panel="Inputs",
        ),
        output_dir: str | None = typer.Option(
            None,
            "--output-dir",
            "-o",
            help="Where to write PDFs (default: backup-<doc_id>).",
            rich_help_panel="Outputs",
        ),
        mode: str | None = typer.Option(
            None,
            "--mode",
            help="Encryption mode: passphrase or recipient.",
            rich_help_panel="Encryption",
        ),
        passphrase: str | None = typer.Option(
            None,
            "--passphrase",
            help="Passphrase to encrypt with.",
            rich_help_panel="Encryption",
        ),
        passphrase_generate: bool = typer.Option(
            False,
            "--generate-passphrase",
            "--passphrase-generate",
            help="Generate a mnemonic passphrase (default if none).",
            rich_help_panel="Encryption",
        ),
        passphrase_words: int | None = typer.Option(
            None,
            "--passphrase-words",
            help="Mnemonic word count for generated passphrases (12/15/18/21/24).",
            rich_help_panel="Encryption",
        ),
        recipient: list[str] = typer.Option(
            None,
            "--recipient",
            help="Recipient public key (age1...).",
            rich_help_panel="Encryption",
        ),
        recipients_file: list[str] = typer.Option(
            None,
            "--recipients-file",
            help="File with recipient public keys.",
            rich_help_panel="Encryption",
        ),
        generate_identity: bool = typer.Option(
            False,
            "--generate-identity",
            help="Generate a new age identity.",
            rich_help_panel="Encryption",
        ),
        sealed: bool = typer.Option(
            False,
            "--sealed",
            help="Seal backup (no new shards later).",
            rich_help_panel="Sharding",
        ),
        shard_threshold: int | None = typer.Option(
            None,
            "--shard-threshold",
            help="Shard threshold (n).",
            rich_help_panel="Sharding",
        ),
        shard_count: int | None = typer.Option(
            None,
            "--shard-count",
            help="Shard count (k).",
            rich_help_panel="Sharding",
        ),
        title: str | None = typer.Option(
            None,
            "--title",
            help="Override main document title.",
            rich_help_panel="Outputs",
        ),
        subtitle: str | None = typer.Option(
            None,
            "--subtitle",
            help="Override main document subtitle.",
            rich_help_panel="Outputs",
        ),
        config: str | None = typer.Option(
            None,
            "--config",
            help="Use this config file.",
            rich_help_panel="Config",
        ),
        paper: str | None = typer.Option(
            None,
            "--paper",
            help="Paper preset (A4/LETTER).",
            rich_help_panel="Config",
        ),
        debug: bool = typer.Option(
            False,
            "--debug",
            help="Show plaintext debug details.",
            rich_help_panel="Debug",
        ),
        debug_max_bytes: int | None = typer.Option(
            None,
            "--debug-max-bytes",
            help=f"Limit debug dump size (default: {DEBUG_MAX_BYTES_DEFAULT}, 0 = no limit).",
            rich_help_panel="Debug",
        ),
        quiet: bool = typer.Option(
            False,
            "--quiet",
            help="Hide non-error output.",
            rich_help_panel="Behavior",
        ),
    ) -> None:
        config_value, paper_value = _resolve_config_and_paper(ctx, config, paper)
        debug_value = debug or bool(_ctx_value(ctx, "debug"))
        debug_max_value = (
            int(_ctx_value(ctx, "debug_max_bytes") or 0)
            if debug_max_bytes is None
            else debug_max_bytes
        )
        quiet_value = quiet or bool(_ctx_value(ctx, "quiet"))
        args = argparse.Namespace(
            config=config_value,
            paper=paper_value,
            input=[str(path) for path in (input or [])],
            input_dir=[str(path) for path in (input_dir or [])],
            base_dir=base_dir,
            output_dir=output_dir,
            mode=mode,
            passphrase=passphrase,
            passphrase_generate=passphrase_generate,
            passphrase_words=passphrase_words,
            recipient=list(recipient or []),
            recipients_file=list(recipients_file or []),
            generate_identity=generate_identity,
            sealed=sealed,
            shard_threshold=shard_threshold,
            shard_count=shard_count,
            title=title,
            subtitle=subtitle,
            debug=debug_value,
            debug_max_bytes=debug_max_value,
            quiet=quiet_value,
        )
        if _should_use_wizard_for_backup(args):
            _run_cli(
                lambda: run_wizard(
                    debug_override=debug_value if debug_value else None,
                    debug_max_bytes=debug_max_value,
                    config_path=config_value,
                    paper_size=paper_value,
                    quiet=quiet_value,
                    args=args,
                ),
                debug=debug_value,
            )
            return
        if not args.input and not args.input_dir and sys.stdin.isatty():
            console_err.print(
                "Input is required for non-interactive backup. Use --input PATH, --input-dir DIR, "
                "pipe data, or run without 'backup' to use the wizard."
            )
            raise typer.Exit(code=2)
        _run_cli(lambda: run_backup_command(args), debug=debug_value)
