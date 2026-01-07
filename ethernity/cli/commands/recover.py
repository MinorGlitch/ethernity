#!/usr/bin/env python3
from __future__ import annotations

import argparse

import typer

from ..core.common import _ctx_value, _resolve_config_and_paper, _run_cli
from ..flows.recover import _should_use_wizard_for_recover, run_recover_command, run_recover_wizard


def register(app: typer.Typer) -> None:
    @app.command(
        help=(
            "Recover data from QR frames or fallback text.\n\n"
            "Examples:\n"
            "  ethernity recover --scan ./scans\n"
            "  ethernity recover --fallback-file fallback.txt --output recovered.bin\n"
            "  ethernity recover --frames-file frames.txt --frames-encoding base64\n"
        )
    )
    def recover(
        ctx: typer.Context,
        fallback_file: str | None = typer.Option(
            None,
            "--fallback-file",
            "-f",
            help="Main fallback text (z-base-32, use - for stdin).",
            rich_help_panel="Inputs",
        ),
        frames_file: str | None = typer.Option(
            None,
            "--frames-file",
            help="Main frame payloads (one per line).",
            rich_help_panel="Inputs",
        ),
        frames_encoding: str = typer.Option(
            "auto",
            "--frames-encoding",
            help="Encoding for frame payloads (auto/base64/base64url/hex).",
            rich_help_panel="Inputs",
        ),
        scan: list[str] = typer.Option(
            None,
            "--scan",
            help="Scan path (image/PDF/dir, repeatable).",
            rich_help_panel="Inputs",
        ),
        passphrase: str | None = typer.Option(
            None,
            "--passphrase",
            help="Passphrase to decrypt with.",
            rich_help_panel="Keys",
        ),
        shard_fallback_file: list[str] = typer.Option(
            None,
            "--shard-fallback-file",
            help="Shard fallback text file (repeatable).",
            rich_help_panel="Inputs",
        ),
        shard_frames_file: list[str] = typer.Option(
            None,
            "--shard-frames-file",
            help="Shard frame payload file (repeatable).",
            rich_help_panel="Inputs",
        ),
        shard_frames_encoding: str = typer.Option(
            "auto",
            "--shard-frames-encoding",
            help="Encoding for shard payloads (auto/base64/base64url/hex).",
            rich_help_panel="Inputs",
        ),
        auth_fallback_file: str | None = typer.Option(
            None,
            "--auth-fallback-file",
            help="Auth fallback text (z-base-32, use - for stdin).",
            rich_help_panel="Inputs",
        ),
        auth_frames_file: str | None = typer.Option(
            None,
            "--auth-frames-file",
            help="Auth frame payloads (one per line).",
            rich_help_panel="Inputs",
        ),
        auth_frames_encoding: str = typer.Option(
            "auto",
            "--auth-frames-encoding",
            help="Encoding for auth payloads (auto/base64/base64url/hex).",
            rich_help_panel="Inputs",
        ),
        output: str | None = typer.Option(
            None,
            "--output",
            "-o",
            help="Output file/dir (default: stdout).",
            rich_help_panel="Output",
        ),
        allow_unsigned: bool = typer.Option(
            False,
            "--allow-unsigned",
            help="Allow recovery without a valid auth frame.",
            rich_help_panel="Verification",
        ),
        assume_yes: bool = typer.Option(
            False,
            "--yes",
            "-y",
            help="Skip confirmation prompts and proceed.",
            rich_help_panel="Behavior",
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
        quiet: bool = typer.Option(
            False,
            "--quiet",
            help="Hide non-error output.",
            rich_help_panel="Behavior",
        ),
    ) -> None:
        config_value, paper_value = _resolve_config_and_paper(ctx, config, paper)
        quiet_value = quiet or bool(_ctx_value(ctx, "quiet"))
        debug_value = bool(_ctx_value(ctx, "debug"))
        args = argparse.Namespace(
            config=config_value,
            paper=paper_value,
            fallback_file=fallback_file,
            frames_file=frames_file,
            frames_encoding=frames_encoding,
            scan=list(scan or []),
            passphrase=passphrase,
            shard_fallback_file=list(shard_fallback_file or []),
            shard_frames_file=list(shard_frames_file or []),
            shard_frames_encoding=shard_frames_encoding,
            auth_fallback_file=auth_fallback_file,
            auth_frames_file=auth_frames_file,
            auth_frames_encoding=auth_frames_encoding,
            output=output,
            allow_unsigned=allow_unsigned,
            assume_yes=assume_yes,
            quiet=quiet_value,
        )
        if _should_use_wizard_for_recover(args):
            _run_cli(lambda: run_recover_wizard(args), debug=debug_value)
            return
        _run_cli(lambda: run_recover_command(args), debug=debug_value)
