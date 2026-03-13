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

from dataclasses import dataclass
from pathlib import Path

from ...formats.envelope_types import EnvelopeManifest, ManifestFile
from ..core.paths import expanduser_cli_path
from ..core.types import RecoverArgs
from ..events import EventSink, active_event_sink, emit_phase, emit_progress, event_session
from ..ui.debug import print_recover_debug
from .recover_flow import decrypt_manifest_and_extract, write_recovered_outputs
from .recover_plan import RecoveryPlan, plan_from_args


@dataclass(frozen=True)
class RecoverShardDirError(ValueError):
    reason: str
    path: str
    message: str

    def __post_init__(self) -> None:
        ValueError.__init__(self, self.message)


@dataclass(frozen=True)
class RecoverExecutionResult:
    plan: RecoveryPlan
    manifest: EnvelopeManifest
    extracted: tuple[tuple[ManifestFile, bytes], ...]
    written_paths: tuple[str, ...]
    single_entry_output_is_directory: bool


def expand_recover_shard_dir(shard_dir: str | None) -> list[str]:
    """Expand shard directory to a list of `.txt` files."""

    if not shard_dir:
        return []
    path = Path(expanduser_cli_path(shard_dir, preserve_stdin=False) or "")
    if not path.exists():
        raise RecoverShardDirError(
            reason="not_found",
            path=shard_dir,
            message=f"shard directory not found: {shard_dir}",
        )
    if not path.is_dir():
        raise RecoverShardDirError(
            reason="invalid_type",
            path=shard_dir,
            message=f"shard-dir must be a directory: {shard_dir}",
        )
    files = sorted(path.glob("*.txt"))
    if not files:
        raise RecoverShardDirError(
            reason="empty",
            path=shard_dir,
            message=f"no .txt files found in shard directory: {shard_dir}",
        )
    return [str(path_item) for path_item in files]


def apply_recover_stdin_default(
    fallback_file: str | None,
    payloads_file: str | None,
    scan: list[str] | None,
    *,
    stdin_is_tty: bool,
) -> str | None:
    if fallback_file or payloads_file or (scan or []) or stdin_is_tty:
        return fallback_file
    return "-"


def prepare_recover_plan(
    args: RecoverArgs,
    *,
    event_sink: EventSink | None = None,
) -> RecoveryPlan:
    with event_session(event_sink):
        emit_phase(phase="plan", label="Resolving recovery inputs")
        plan = plan_from_args(args)
        emit_progress(
            phase="plan",
            current=1,
            total=1,
            unit="step",
            details={
                "main_frame_count": len(plan.main_frames),
                "auth_frame_count": len(plan.auth_frames),
                "shard_frame_count": len(plan.shard_frames),
            },
        )
        return plan


def execute_recover_plan(
    plan: RecoveryPlan,
    *,
    quiet: bool,
    debug: bool = False,
    debug_max_bytes: int = 0,
    debug_reveal_secrets: bool = False,
    event_sink: EventSink | None = None,
) -> RecoverExecutionResult:
    with event_session(event_sink):
        emit_phase(phase="decrypt", label="Decrypting and extracting payload")
        manifest, extracted = decrypt_manifest_and_extract(plan, quiet=quiet, debug=debug)
        emit_progress(
            phase="decrypt",
            current=1,
            total=1,
            unit="step",
            details={"file_count": len(extracted), "manifest_file_count": len(manifest.files)},
        )
        if debug:
            print_recover_debug(
                manifest=manifest,
                extracted=extracted,
                ciphertext=plan.ciphertext,
                passphrase=plan.passphrase,
                auth_status=plan.auth_status,
                allow_unsigned=plan.allow_unsigned,
                output_path=plan.output_path,
                debug_max_bytes=debug_max_bytes,
                reveal_secrets=debug_reveal_secrets,
                stderr=active_event_sink() is not None,
            )

        single_entry_output_is_directory = (
            plan.output_path is not None
            and len(extracted) == 1
            and manifest.input_origin in {"directory", "mixed"}
        )
        emit_phase(phase="write", label="Writing recovered files")
        written_paths = write_recovered_outputs(
            extracted,
            output_path=plan.output_path,
            auth_status=plan.auth_status,
            allow_unsigned=plan.allow_unsigned,
            quiet=quiet,
            single_entry_output_is_directory=single_entry_output_is_directory,
        )
        return RecoverExecutionResult(
            plan=plan,
            manifest=manifest,
            extracted=tuple(extracted),
            written_paths=tuple(written_paths),
            single_entry_output_is_directory=single_entry_output_is_directory,
        )


__all__ = [
    "RecoverExecutionResult",
    "RecoverShardDirError",
    "apply_recover_stdin_default",
    "execute_recover_plan",
    "expand_recover_shard_dir",
    "prepare_recover_plan",
]
