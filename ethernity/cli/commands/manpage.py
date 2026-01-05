#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

import typer

from ..ui import console


def register(app: typer.Typer) -> None:
    @app.command(help="Generate a manpage for the CLI.")
    def manpage(
        output: Path | None = typer.Option(
            None,
            "--output",
            "-o",
            help="Write the manpage to a file (default: stdout).",
        )
    ) -> None:
        import datetime
        import click

        command = typer.main.get_command(app)
        ctx = click.Context(command)
        help_text = command.get_help(ctx)
        date = datetime.datetime.utcnow().strftime("%Y-%m-%d")
        man = "\n".join(
            [
                f".TH ETHERNITY 1 \"{date}\" \"ethernity\" \"User Commands\"",
                ".SH NAME",
                "ethernity \\- secure paper backups and recovery tool",
                ".SH SYNOPSIS",
                ".nf",
                help_text,
                ".fi",
            ]
        )
        if output:
            output.write_text(man, encoding="utf-8")
        else:
            console.print(man, markup=False)
