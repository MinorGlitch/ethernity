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

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from rich.progress import Progress

from ethernity.cli.features.backup.execution import run_backup as _run_backup
from ethernity.cli.features.backup.planning import plan_from_args
from ethernity.cli.shared import api_codes
from ethernity.cli.shared.events import EventSink, emit_phase, emit_progress, event_session
from ethernity.cli.shared.io.inputs import _load_input_files
from ethernity.cli.shared.log import _warn
from ethernity.cli.shared.plan import _validate_backup_args
from ethernity.cli.shared.types import BackupArgs, BackupResult, InputFile
from ethernity.config import AppConfig, apply_template_design, load_app_config
from ethernity.core.models import DocumentPlan, SigningSeedMode


@dataclass(frozen=True)
class PreparedBackupRun:
    args: BackupArgs
    config: AppConfig
    plan: DocumentPlan
    input_files: tuple[InputFile, ...]
    base_dir: Path | None
    input_origin: Literal["file", "directory", "mixed"]
    input_roots: tuple[str, ...]


def apply_qr_chunk_size_override(config: AppConfig, qr_chunk_size: int | None) -> AppConfig:
    """Override the configured preferred QR chunk size when requested."""

    if qr_chunk_size is None:
        return config
    return replace(config, qr_chunk_size=qr_chunk_size)


def prepare_backup_run(
    args: BackupArgs,
    *,
    input_progress: Progress | None = None,
    event_sink: EventSink | None = None,
) -> PreparedBackupRun:
    with event_session(event_sink):
        emit_phase(phase="plan", label="Resolving backup configuration")
        config = load_app_config(args.config, paper_size=args.paper)
        config = apply_template_design(config, args.design)
        config = apply_qr_chunk_size_override(config, args.qr_chunk_size)
        _validate_backup_args(args)
        plan = plan_from_args(args)
        if plan.sealed and plan.signing_seed_mode == SigningSeedMode.SHARDED:
            _warn(
                "Signing-key sharding is disabled for sealed backups.",
                quiet=args.quiet,
                code=api_codes.BACKUP_SIGNING_KEY_SHARDING_DISABLED,
            )

        emit_phase(phase="input", label="Loading backup inputs")
        input_files, resolved_base, input_origin, input_roots = _load_input_files(
            list(args.input or []),
            list(args.input_dir or []),
            args.base_dir,
            allow_stdin=True,
            progress=input_progress,
        )
        emit_progress(
            phase="input",
            current=len(input_files),
            total=len(input_files),
            unit="files",
            details={"input_origin": input_origin, "input_roots": input_roots},
        )
        return PreparedBackupRun(
            args=args,
            config=config,
            plan=plan,
            input_files=tuple(input_files),
            base_dir=resolved_base,
            input_origin=input_origin,
            input_roots=tuple(input_roots),
        )


def execute_prepared_backup(
    prepared: PreparedBackupRun,
    *,
    event_sink: EventSink | None = None,
) -> BackupResult:
    with event_session(event_sink):
        emit_phase(phase="backup", label="Generating backup documents")
        return _run_backup(
            input_files=list(prepared.input_files),
            base_dir=prepared.base_dir,
            output_dir=prepared.args.output_dir,
            output_dir_existing_parent=prepared.args.output_dir_existing_parent,
            layout_debug_dir=prepared.args.layout_debug_dir,
            input_origin=prepared.input_origin,
            input_roots=list(prepared.input_roots),
            plan=prepared.plan,
            passphrase=prepared.args.passphrase,
            passphrase_words=prepared.args.passphrase_words,
            config=prepared.config,
            debug=prepared.args.debug,
            debug_max_bytes=prepared.args.debug_max_bytes,
            debug_reveal_secrets=prepared.args.debug_reveal_secrets,
            quiet=prepared.args.quiet,
        )


__all__ = [
    "PreparedBackupRun",
    "apply_qr_chunk_size_override",
    "execute_prepared_backup",
    "prepare_backup_run",
]
