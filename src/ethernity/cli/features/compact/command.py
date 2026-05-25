#!/usr/bin/env python3
# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

import functools
from pathlib import Path
from typing import Annotated

import typer

from ethernity.cli.features.compact.service import run_compact
from ethernity.cli.shared.common import (
    _ctx_state,
    _paper_callback,
    _resolve_config_and_paper,
    _run_cli,
)
from ethernity.cli.shared.types import BackupResult, CompactArgs
from ethernity.cli.shared.ui_api import (
    build_kv_table,
    build_outputs_tree,
    console,
    console_err,
    panel,
    print_completion_panel,
)
from ethernity.config import BackupDefaults

_COMPACT_HELP = (
    "Compact a backup root folder (writable backup root) into a fresh standalone backup.\n\n"
    "Examples:\n"
    "  ethernity compact --root-dir backup-aa11 --output-dir compacted\n"
    "  ethernity compact --root-dir backup-aa11 --output-dir compacted --design forge\n"
)


def register(app: typer.Typer) -> None:
    app.command(help=_COMPACT_HELP)(compact)


def _print_compact_summary(
    result: BackupResult,
    *,
    root_dir: str,
    quiet: bool,
) -> None:
    if quiet:
        return
    output_dir = str(Path(result.qr_path).parent)
    console.print()
    console.print(
        panel(
            "Outputs",
            build_outputs_tree(
                result.qr_path,
                result.recovery_path,
                tuple(result.shard_paths),
                tuple(result.signing_key_shard_paths),
                result.kit_index_path,
            ),
        )
    )
    console.print(
        panel(
            "Compact summary",
            build_kv_table(
                [
                    ("Source root", root_dir),
                    ("Output dir", output_dir),
                    ("Doc ID", result.doc_id.hex()),
                ]
            ),
        )
    )


def _print_completion_actions(
    result: BackupResult,
    *,
    output_dir: str,
    quiet: bool,
) -> None:
    if quiet:
        return
    actions = [
        f"Saved compacted standalone backup to {output_dir}",
        "Keep the prior root and extension chain until the compacted backup is verified.",
    ]
    if result.shard_paths:
        actions.append(f"Store {len(result.shard_paths)} passphrase shard documents separately.")
    if result.signing_key_shard_paths:
        actions.append(
            f"Store {len(result.signing_key_shard_paths)} signing-key shard documents separately."
        )
    actions.append("Use the compacted backup as the new standalone root for future extensions.")
    print_completion_panel("Compact complete", actions, quiet=quiet)


def run_compact_command(args: CompactArgs, *, debug: bool = False) -> int:
    _ = debug
    result = run_compact(args)
    output_dir = str(Path(result.qr_path).parent)
    _print_compact_summary(result, root_dir=args.root_dir or "", quiet=args.quiet)
    _print_completion_actions(result, output_dir=output_dir, quiet=args.quiet)
    return 0


def compact(
    ctx: typer.Context,
    root_dir: Annotated[
        Path,
        typer.Option(
            "--root-dir",
            help="Backup root folder (writable backup root) to compact.",
            rich_help_panel="Inputs",
        ),
    ],
    shard_fallback_file: Annotated[
        list[str] | None,
        typer.Option(
            "--shard-fallback-file",
            help="Fallback text file containing passphrase shard lines (repeatable).",
            rich_help_panel="Unlock",
        ),
    ] = None,
    shard_payloads_file: Annotated[
        list[str] | None,
        typer.Option(
            "--shard-payloads-file",
            help="Text file containing one passphrase shard payload per line (repeatable).",
            rich_help_panel="Unlock",
        ),
    ] = None,
    shard_scan: Annotated[
        list[str] | None,
        typer.Option(
            "--shard-scan",
            help="Passphrase shard document image/PDF to scan (repeatable).",
            rich_help_panel="Unlock",
        ),
    ] = None,
    auth_fallback_file: Annotated[
        str | None,
        typer.Option(
            "--auth-fallback-file",
            help="Fallback text file containing the AUTH payload lines.",
            rich_help_panel="Unlock",
        ),
    ] = None,
    auth_payloads_file: Annotated[
        str | None,
        typer.Option(
            "--auth-payloads-file",
            help="Text file containing one AUTH payload line.",
            rich_help_panel="Unlock",
        ),
    ] = None,
    passphrase: Annotated[
        str | None,
        typer.Option(
            "--passphrase",
            help="Passphrase to decrypt and compact with.",
            rich_help_panel="Unlock",
        ),
    ] = None,
    output_dir: Annotated[
        str | None,
        typer.Option(
            "--output-dir",
            "-o",
            help="Where to write the compacted standalone backup.",
            rich_help_panel="Outputs",
        ),
    ] = None,
    quiet: Annotated[
        bool,
        typer.Option(
            "--quiet",
            help="Hide non-error output.",
            rich_help_panel="Behavior",
        ),
    ] = False,
    config: Annotated[
        str | None,
        typer.Option(
            "--config",
            help="Use this config file.",
            rich_help_panel="Config",
        ),
    ] = None,
    paper: Annotated[
        str | None,
        typer.Option(
            "--paper",
            help="Paper size override (A4/Letter).",
            callback=_paper_callback,
            rich_help_panel="Config",
        ),
    ] = None,
    design: Annotated[
        str | None,
        typer.Option(
            "--design",
            help="Template design folder (auto-discovered under templates/).",
            rich_help_panel="Config",
        ),
    ] = None,
    qr_chunk_size: Annotated[
        int | None,
        typer.Option(
            "--qr-chunk-size",
            help=(
                "Preferred ciphertext bytes per QR frame. Lower values create more codes "
                "but easier scanning; renderer may reduce to fit."
            ),
            rich_help_panel="Config",
        ),
    ] = None,
    layout_debug_dir: Annotated[
        str | None,
        typer.Option(
            "--layout-debug-dir",
            help=(
                "Write per-document layout diagnostics JSON files to this directory "
                "(for pagination/capacity debugging)."
            ),
            rich_help_panel="Advanced",
        ),
    ] = None,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            help="Show traceback details on failure.",
            rich_help_panel="Debug",
        ),
    ] = False,
) -> None:
    state = _ctx_state(ctx)
    defaults = state.backup_defaults if state is not None else BackupDefaults()
    config_value, paper_value = _resolve_config_and_paper(ctx, config, paper)
    output_dir_value = output_dir if output_dir is not None else defaults.output_dir
    if output_dir_value is None:
        console_err.print("[error]Use --output-dir PATH or configure backup.output_dir.[/error]")
        raise typer.Exit(code=2)

    quiet_value = quiet or (state.quiet if state is not None else False)
    args = CompactArgs(
        config=config_value,
        paper=paper_value,
        design=design or (state.design if state is not None else None),
        root_dir=str(root_dir),
        output_dir=output_dir_value,
        shard_fallback_file=shard_fallback_file,
        shard_payloads_file=shard_payloads_file,
        shard_scan=shard_scan,
        auth_fallback_file=auth_fallback_file,
        auth_payloads_file=auth_payloads_file,
        layout_debug_dir=layout_debug_dir,
        qr_chunk_size=qr_chunk_size,
        passphrase=passphrase,
        quiet=quiet_value,
    )
    debug_value = debug or bool(state and state.debug)
    runner = functools.partial(run_compact_command, args, debug=debug_value)
    _run_cli(runner, debug=debug_value)
