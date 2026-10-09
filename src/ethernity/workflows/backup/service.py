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

from ethernity.config import AppConfig, apply_render_style, load_app_config
from ethernity.core.models import DocumentPlan, SigningSeedMode
from ethernity.render.types import DocumentOrigin
from ethernity.workflows.backup.execution import run_backup as _run_backup
from ethernity.workflows.backup.planning import plan_from_request
from ethernity.workflows.shared import issue_codes
from ethernity.workflows.shared.backup_validation import validate_backup_request
from ethernity.workflows.shared.events import EventSink, emit_phase, emit_progress, event_session
from ethernity.workflows.shared.file_inputs import InputLoadProgress, load_input_files
from ethernity.workflows.shared.notices import warn
from ethernity.workflows.shared.operation_types import (
    BackupResult,
    InputFile,
)
from ethernity.workflows.shared.requests import BackupRequest


@dataclass(frozen=True)
class PreparedBackupRun:
    request: BackupRequest
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
    request: BackupRequest,
    *,
    input_progress: InputLoadProgress | None = None,
    event_sink: EventSink | None = None,
) -> PreparedBackupRun:
    with event_session(event_sink):
        emit_phase(phase="configuration", label="Resolving backup configuration")
        config = load_app_config(request.config_path, paper_size=request.paper_size)
        config = apply_render_style(config, request.design)
        config = apply_qr_chunk_size_override(config, request.qr_chunk_size)
        validate_backup_request(request)
        plan = plan_from_request(request)
        if plan.sealed and plan.signing_seed_mode == SigningSeedMode.SHARDED:
            warn(
                "Signing-key sharding is disabled for sealed backups.",
                quiet=request.quiet,
                code=issue_codes.BACKUP_SIGNING_KEY_SHARDING_DISABLED,
            )

        emit_phase(phase="input", label="Loading backup inputs")
        input_files, resolved_base, input_origin, input_roots = load_input_files(
            request.input_paths,
            request.input_dirs,
            request.base_dir,
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
            request=request,
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
            output_dir=prepared.request.output_dir,
            layout_debug_dir=prepared.request.layout_debug_dir,
            input_origin=prepared.input_origin,
            input_roots=list(prepared.input_roots),
            plan=prepared.plan,
            passphrase=prepared.request.passphrase,
            passphrase_words=prepared.request.passphrase_words,
            config=prepared.config,
            render_origin=DocumentOrigin(kind="root_backup"),
            debug=prepared.request.debug,
            debug_max_bytes=prepared.request.debug_max_bytes,
            debug_reveal_secrets=prepared.request.debug_reveal_secrets,
            quiet=prepared.request.quiet,
        )


__all__ = [
    "PreparedBackupRun",
    "apply_qr_chunk_size_override",
    "execute_prepared_backup",
    "prepare_backup_run",
]
