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

"""Prepare extension documents for publication."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast

from ethernity.crypto import encrypt_bytes_with_passphrase
from ethernity.crypto.document_identity import doc_id_and_hash_from_ciphertext
from ethernity.extensions.build import build_extension
from ethernity.extensions.resources import (
    require_chain_resource_limits,
    require_decoded_chunk_resource_limit,
)
from ethernity.extensions.staging import (
    create_extension_staging_paths,
    extension_output_directory_name,
)
from ethernity.workflows.add_files.errors import AddFilesIssue, AddFilesWorkflowError
from ethernity.workflows.add_files.models import (
    EncryptedExtension,
    ExtensionPublication,
    PreparedAddFilesRun,
)
from ethernity.workflows.add_files.planning import ResolvedAddFilesState, resolve_add_files_state
from ethernity.workflows.add_files.request import AddFilesRequest
from ethernity.workflows.shared import issue_codes


def prepare_add_files_run(request: AddFilesRequest) -> PreparedAddFilesRun:
    """Validate an Add Files request and retain its authenticated chain state."""

    _require_selected_input(request)

    return prepare_add_files_run_from_state(request, resolve_add_files_state(request))


def prepare_add_files_run_from_state(
    request: AddFilesRequest,
    resolved: ResolvedAddFilesState,
) -> PreparedAddFilesRun:
    """Prepare Add Files from an already resolved planning state."""

    _require_selected_input(request)

    if resolved.blocking_issues:
        _raise_planning_issue(resolved.blocking_issues[0])
    plan = resolved.plan
    if plan is None:
        raise AddFilesWorkflowError(
            code=issue_codes.RUNTIME_ERROR,
            message="Add Files planning did not produce a publishable update plan",
        )

    diff = plan.diff

    if not diff.changed_paths and not diff.new_paths:
        raise AddFilesWorkflowError(
            code=issue_codes.ADD_FILES_NO_CHANGES,
            message="selected files match the current backup; there is nothing to update",
        )

    selected_input = resolved.selected_input
    if selected_input is None:
        raise AddFilesWorkflowError(
            code=issue_codes.RUNTIME_ERROR,
            message="Add Files planning did not retain the selected input",
        )
    validated_chain = resolved.validated_chain
    if validated_chain is None:
        raise AddFilesWorkflowError(
            code=issue_codes.RUNTIME_ERROR,
            message="Add Files planning did not retain the authenticated backup state",
        )
    if resolved.resolved_passphrase is None or not resolved.resolved_passphrase:
        raise AddFilesWorkflowError(
            code=issue_codes.RUNTIME_ERROR,
            message="Add Files planning did not retain the backup passphrase",
        )

    if request.output_dir is None:
        request = replace(
            request,
            output_dir=str(
                Path.cwd()
                / extension_output_directory_name(
                    plan.parent.root_doc_hash, plan.parent.head_index + 1
                )
            ),
        )

    return PreparedAddFilesRun(
        request=request,
        plan=plan,
        selected_input=selected_input,
        validated_chain=validated_chain,
        chain_document_count=resolved.chain_document_count,
        chain_ciphertext_bytes=resolved.chain_ciphertext_bytes,
        chain_decoded_chunk_bytes=resolved.chain_decoded_chunk_bytes,
        encryption_passphrase=resolved.resolved_passphrase,
        source_frames=resolved.source_frames,
    )


def _require_selected_input(request: AddFilesRequest) -> None:
    if not request.input_paths and not request.input_directories:
        raise AddFilesWorkflowError(
            code=issue_codes.ADD_FILES_INPUT_REQUIRED,
            message="Add Files requires at least one explicit file or folder selection",
        )


def _raise_planning_issue(issue: AddFilesIssue) -> None:
    raise AddFilesWorkflowError(
        code=issue.code,
        message=issue.message,
        details=cast(dict[str, object], issue.details),
    )


def assemble_prepared_extension_document(
    prepared: PreparedAddFilesRun,
):
    """Assemble an extension document from a prepared Add Files request."""

    require_chain_resource_limits(
        document_count=prepared.chain_document_count + 1,
        total_ciphertext_bytes=prepared.chain_ciphertext_bytes,
        operation="extension append",
    )
    try:
        return build_extension(
            prepared.validated_chain, prepared.selected_input, update_mode=prepared.plan.update_mode
        )
    except ValueError as exc:
        raise AddFilesWorkflowError(
            code=issue_codes.CHAIN_INVALID,
            message=f"extension candidate verification failed: {exc}",
        ) from exc


def encrypt_prepared_extension_document(
    prepared: PreparedAddFilesRun,
) -> EncryptedExtension:
    """Build and encrypt an extension document using the resolved chain passphrase."""

    built = assemble_prepared_extension_document(prepared)
    require_decoded_chunk_resource_limit(
        decoded_chunk_bytes=(
            prepared.chain_decoded_chunk_bytes + built.document.inline_chunk_raw_bytes
        ),
        operation="extension append",
    )
    plaintext = built.document.encode()
    ciphertext, _passphrase = encrypt_bytes_with_passphrase(
        plaintext,
        passphrase=prepared.encryption_passphrase,
    )
    require_chain_resource_limits(
        document_count=prepared.chain_document_count + 1,
        total_ciphertext_bytes=prepared.chain_ciphertext_bytes + len(ciphertext),
        operation="extension append",
    )
    doc_id, doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
    return EncryptedExtension(
        built=built,
        plaintext=plaintext,
        ciphertext=ciphertext,
        doc_id=doc_id,
        doc_hash=doc_hash,
    )


def prepare_extension_publish(
    prepared: PreparedAddFilesRun,
    *,
    encrypted: EncryptedExtension,
    nonce: str,
    output_dir: str | Path | None = None,
) -> ExtensionPublication:
    """Assign the staged output paths for one encrypted extension."""

    destination = output_dir or prepared.request.output_dir
    if not destination:
        raise AddFilesWorkflowError(
            code=issue_codes.RUNTIME_ERROR,
            message="Add Files requires an output directory",
        )
    paths = create_extension_staging_paths(
        destination,
        index=prepared.next_index,
        doc_id_hex=encrypted.doc_id.hex(),
        nonce=nonce,
    )
    return ExtensionPublication(
        prepared=prepared,
        encrypted=encrypted,
        paths=paths,
    )


__all__ = [
    "assemble_prepared_extension_document",
    "encrypt_prepared_extension_document",
    "prepare_add_files_run_from_state",
    "prepare_add_files_run",
    "prepare_extension_publish",
]
