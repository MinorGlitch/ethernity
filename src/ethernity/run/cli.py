from __future__ import annotations

from pathlib import Path

import click

from ethernity.run.command_registry import RUN_COMMANDS
from ethernity.run.context import bind_config_path

_HELP_SETTINGS = {"help_option_names": ["-h", "--help"]}


@click.group(context_settings=_HELP_SETTINGS)
@click.option(
    "--config",
    "config_path",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Use this configuration file.",
)
@click.pass_context
def cli(ctx: click.Context, config_path: Path | None) -> None:
    """Run scriptable Ethernity tasks."""

    bind_config_path(ctx, config_path)


for command in RUN_COMMANDS:
    cli.add_command(command)


def main() -> None:
    cli()


__all__ = ["cli", "main"]
