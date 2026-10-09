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
from hashlib import sha256
from typing import Literal

from ethernity.crypto.age_policy import recovery_kdf_budget
from ethernity.formats.manifest import BackupManifest, ManifestFile
from ethernity.workflows.recovery.execution import decrypt_manifest_extract_selection
from ethernity.workflows.recovery.planning import RecoveryPlan, plan_from_request
from ethernity.workflows.shared.events import (
    EventSink,
    active_event_sink,
    emit_phase,
    emit_progress,
    emit_written_file,
    event_session,
)
from ethernity.workflows.shared.outputs import (
    single_entry_uses_directory_output,
    write_recovered_outputs,
)
from ethernity.workflows.shared.paths import display_parent_path
from ethernity.workflows.shared.requests import RecoveryRequest


def print_recover_debug(**_: object) -> None:
    return


@dataclass(frozen=True)
class RecoverExecutionResult:
    plan: RecoveryPlan
    manifest: BackupManifest
    extracted: tuple[tuple[ManifestFile, bytes], ...]
    written_paths: tuple[str, ...]
    file_payloads: tuple[dict[str, object], ...]
    output_path: str
    output_path_kind: Literal["file", "directory", "stdout"]
    single_entry_output_is_directory: bool
    requested_extension_index: int | None = None
    requested_extension_doc_hash: str | None = None
    expected_head_doc_hash: str | None = None
    selected_extension_index: int | None = None
    selected_extension_doc_hash: str | None = None
    trust_basis: Literal["matched_expected_head", "internally_consistent", "unauthenticated"] = (
        "internally_consistent"
    )
    signing_key_verified: bool = False


def prepare_recover_plan(
    args: RecoveryRequest,
    *,
    event_sink: EventSink | None = None,
) -> RecoveryPlan:
    with (
        event_session(event_sink),
        recovery_kdf_budget(),
    ):
        emit_phase(phase="plan", label="Resolving recovery inputs")
        plan = plan_from_request(args)
        plan.emit_plan_progress()
        return plan


def execute_recover_plan(
    plan: RecoveryPlan,
    *,
    quiet: bool,
    debug: bool = False,
    debug_max_bytes: int = 0,
    debug_reveal_secrets: bool = False,
    emit_written_files: bool = True,
    event_sink: EventSink | None = None,
) -> RecoverExecutionResult:
    with (
        event_session(event_sink),
        recovery_kdf_budget(),
    ):
        file_payloads: list[dict[str, object]] = []

        def _on_file_written(
            entry: object,
            data: bytes,
            written_path: str,
            index: int,
            total: int,
        ) -> None:
            manifest_entry = entry if isinstance(entry, ManifestFile) else None
            manifest_path = (
                manifest_entry.path
                if manifest_entry is not None
                else getattr(entry, "path", "payload.bin")
            )
            file_payload = {
                "manifest_path": manifest_path,
                "output_path": written_path,
                "size": len(data),
                "sha256": sha256(data).hexdigest(),
                "mtime": getattr(manifest_entry, "mtime", getattr(entry, "mtime", None)),
            }
            file_payloads.append(file_payload)
            emit_progress(
                phase="write",
                current=index,
                total=total,
                unit="files",
                label=f"Wrote recovered file {index} of {total}",
                details={"output_path": written_path, "manifest_path": manifest_path},
            )
            if emit_written_files:
                emit_written_file(kind="recovered_file", path=written_path, details=file_payload)

        emit_phase(phase="decrypt", label="Decrypting and extracting payload")
        decrypted = decrypt_manifest_extract_selection(plan, quiet=quiet, debug=debug)
        manifest = decrypted.manifest
        extracted = list(decrypted.extracted)
        authenticated = plan.auth_status == "verified" and plan.auth_payload is not None
        trusted_head_matched = authenticated and plan.expected_head_doc_hash is not None
        trust_basis: Literal["matched_expected_head", "internally_consistent", "unauthenticated"]
        if not authenticated:
            trust_basis = "unauthenticated"
        elif trusted_head_matched:
            trust_basis = "matched_expected_head"
        else:
            trust_basis = "internally_consistent"
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
        single_entry_output_is_directory = single_entry_uses_directory_output(
            plan.output_path,
            single_entry_output_is_directory=single_entry_output_is_directory,
        )
        emit_phase(phase="write", label="Writing recovered files")
        written_paths = write_recovered_outputs(
            plan.output_path,
            extracted,
            single_entry_output_is_directory=single_entry_output_is_directory,
            on_entry_written=_on_file_written,
        )
        if written_paths:
            if len(written_paths) == 1 and not single_entry_output_is_directory:
                emitted_output_path = written_paths[0]
                output_path_kind: Literal["file", "directory", "stdout"] = "file"
            else:
                emitted_output_path = plan.output_path or display_parent_path(written_paths[0])
                output_path_kind = "directory"
        else:
            emitted_output_path = plan.output_path or "-"
            output_path_kind = "stdout"
        return RecoverExecutionResult(
            plan=plan,
            manifest=manifest,
            extracted=tuple(extracted),
            written_paths=tuple(written_paths),
            file_payloads=tuple(file_payloads),
            output_path=emitted_output_path,
            output_path_kind=output_path_kind,
            single_entry_output_is_directory=single_entry_output_is_directory,
            requested_extension_index=getattr(plan, "extension_index", None),
            requested_extension_doc_hash=getattr(plan, "extension_doc_hash", None),
            expected_head_doc_hash=getattr(plan, "expected_head_doc_hash", None),
            selected_extension_index=decrypted.selected_extension_index,
            selected_extension_doc_hash=decrypted.selected_extension_doc_hash,
            trust_basis=trust_basis,
            signing_key_verified=trusted_head_matched and manifest.signing_seed is not None,
        )


__all__ = [
    "RecoverExecutionResult",
    "execute_recover_plan",
    "prepare_recover_plan",
]
