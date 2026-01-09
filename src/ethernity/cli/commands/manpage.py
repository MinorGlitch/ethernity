#!/usr/bin/env python3
from __future__ import annotations

import datetime
from pathlib import Path

import click
import typer

from ..api import console


def register(app: typer.Typer) -> None:
    app.command(help="Generate a manpage for the CLI.")(manpage)


def manpage(
    ctx: typer.Context,
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Write the manpage to a file (default: stdout).",
    ),
) -> None:
    root_ctx = ctx.find_root()
    command = root_ctx.command
    help_text = command.get_help(click.Context(command))
    date = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    man = "\n".join(
        [
            f'.TH ETHERNITY 1 "{date}" "ethernity" "User Commands"',
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
