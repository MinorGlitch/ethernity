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

"""Preparation helpers for extension execution."""

from __future__ import annotations

from typing import cast

from ethernity.crypto import encrypt_bytes_with_passphrase
from ethernity.crypto.document_identity import doc_id_and_hash_from_ciphertext
from ethernity.extensions.build import Chunker, build_extension
from ethernity.extensions.resources import (
    require_chain_resource_limits,
    require_decoded_chunk_resource_limit,
)
from ethernity.extensions.staging import (
    ExtensionPublishPolicy,
    create_staged_extension_artifact_plan,
)
from ethernity.workflows.extension.errors import ExtensionIssue, ExtensionWorkflowError
from ethernity.workflows.extension.models import (
    EXTENSION_INPUT_REQUIRED,
    EXTENSION_NO_CHANGES,
    EncryptedPreparedExtension,
    PreparedExtendRun,
    PreparedExtensionPublishPlan,
)
from ethernity.workflows.extension.planning import ResolvedExtendState, resolve_extend_state
from ethernity.workflows.extension.request import ExtensionRequest
from ethernity.workflows.shared import api_codes


def prepare_extend_run(args: ExtensionRequest) -> PreparedExtendRun:
    """Validate extend preconditions and summarize the pending change set."""

    if not args.input_paths and not args.input_directories:
        raise ExtensionWorkflowError(
            code=EXTENSION_INPUT_REQUIRED,
            message="extend requires at least one explicit --input or --input-dir selection",
        )

    return prepare_extend_run_from_state(args, resolve_extend_state(args))


def prepare_extend_run_from_state(
    args: ExtensionRequest,
    resolved: ResolvedExtendState,
) -> PreparedExtendRun:
    """Validate extend preconditions from an already resolved planning state."""

    if not args.input_paths and not args.input_directories:
        raise ExtensionWorkflowError(
            code=EXTENSION_INPUT_REQUIRED,
            message="extend requires at least one explicit --input or --input-dir selection",
        )

    plan = resolved.plan
    if plan is None:
        if resolved.issues:
            _raise_planning_issue(resolved.issues[0])
        raise ExtensionWorkflowError(
            code="RUNTIME_ERROR",
            message="extend planning did not produce an execution-grade typed plan",
        )
    if plan.issues:
        _raise_planning_issue(plan.issues[0])

    diff = plan.diff

    if diff.missing_paths:
        raise ExtensionWorkflowError(
            code=api_codes.DELETE_NOT_SUPPORTED,
            message=(
                "selected scope omits previously backed paths; Add Files cannot delete or "
                "rename paths. Create a New Backup from the desired files and retire the "
                "superseded carriers"
            ),
            details={"missing_paths": list(diff.missing_paths)},
        )

    if not diff.changed_paths and not diff.new_paths:
        raise ExtensionWorkflowError(
            code=EXTENSION_NO_CHANGES,
            message="selected scope matches the current chain state; nothing to extend",
        )

    loaded_scope = resolved.loaded_scope
    if loaded_scope is None:
        raise ExtensionWorkflowError(
            code="RUNTIME_ERROR",
            message="extend planning did not retain the selected scope",
        )
    current_state = resolved.current_state
    if current_state is None:
        raise ExtensionWorkflowError(
            code="RUNTIME_ERROR",
            message="extend planning did not retain the current chain state",
        )
    validated_chain_state = resolved.validated_chain_state
    if validated_chain_state is None:
        raise ExtensionWorkflowError(
            code="RUNTIME_ERROR",
            message="extend planning did not retain authenticated replay state",
        )
    if (
        resolved.resolved_passphrase is None
        or not resolved.resolved_passphrase
        or resolved.chunking is None
    ):
        raise ExtensionWorkflowError(
            code="RUNTIME_ERROR",
            message="extend planning did not resolve chain lineage for execution",
        )

    return PreparedExtendRun(
        args=args,
        plan=plan,
        loaded_scope=loaded_scope,
        current_state=current_state,
        validated_chain_state=validated_chain_state,
        chain_document_count=resolved.chain_document_count,
        chain_ciphertext_bytes=resolved.chain_ciphertext_bytes,
        chain_decoded_chunk_bytes=resolved.chain_decoded_chunk_bytes,
        encryption_passphrase=resolved.resolved_passphrase,
        chunking=resolved.chunking,
        root_passphrase_shard_threshold=resolved.root_passphrase_shard_threshold,
        root_passphrase_shard_count=resolved.root_passphrase_shard_count,
        input_origin=loaded_scope.input_origin,
        input_roots=loaded_scope.input_roots,
        unlock_passphrase_shard_threshold=resolved.unlock_passphrase_shard_threshold,
        unlock_passphrase_shard_count=resolved.unlock_passphrase_shard_count,
    )


def _raise_planning_issue(issue: ExtensionIssue) -> None:
    raise ExtensionWorkflowError(
        code=issue.code,
        message=issue.message,
        details=cast(dict[str, object], issue.details),
    )


def assemble_prepared_extension_document(
    prepared: PreparedExtendRun,
    *,
    chunker: Chunker,
):
    """Assemble an extension envelope from a prepared extend run."""

    require_chain_resource_limits(
        document_count=prepared.chain_document_count + 1,
        total_ciphertext_bytes=prepared.chain_ciphertext_bytes,
        operation="extension append",
    )
    del chunker  # The public builder always uses the chain's canonical chunking implementation.
    try:
        return build_extension(prepared.validated_chain_state, prepared.loaded_scope)
    except ValueError as exc:
        raise ExtensionWorkflowError(
            code="CHAIN_INVALID",
            message=f"extension candidate verification failed: {exc}",
        ) from exc


def encrypt_prepared_extension_document(
    prepared: PreparedExtendRun,
    *,
    chunker: Chunker,
) -> EncryptedPreparedExtension:
    """Build and encrypt an extension document using the resolved chain passphrase."""

    built = assemble_prepared_extension_document(prepared, chunker=chunker)
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
    return EncryptedPreparedExtension(
        built=built,
        plaintext=plaintext,
        ciphertext=ciphertext,
        doc_id=doc_id,
        doc_hash=doc_hash,
    )


def prepare_staged_extension_publish(
    prepared: PreparedExtendRun,
    *,
    chunker: Chunker,
    nonce: str,
    publish_policy: ExtensionPublishPolicy,
) -> PreparedExtensionPublishPlan:
    """Build, encrypt, and assign canonical staged artifact targets for an extension publish."""

    if not prepared.args.publish_root:
        raise ExtensionWorkflowError(
            code="RUNTIME_ERROR",
            message="extend execution requires a root_dir for staged publish planning",
        )

    encrypted = encrypt_prepared_extension_document(prepared, chunker=chunker)
    artifacts = create_staged_extension_artifact_plan(
        prepared.args.publish_root,
        index=prepared.next_index,
        doc_id_hex=encrypted.doc_id.hex(),
        nonce=nonce,
        publish_policy=publish_policy,
        publish_layout="loose" if prepared.args.scan_paths else "canonical",
        allow_missing_root=bool(prepared.args.scan_paths),
        require_empty_root=bool(prepared.args.scan_paths),
    )
    return PreparedExtensionPublishPlan(
        prepared=prepared,
        encrypted=encrypted,
        publish_policy=publish_policy,
        artifacts=artifacts,
    )


__all__ = [
    "assemble_prepared_extension_document",
    "encrypt_prepared_extension_document",
    "prepare_extend_run_from_state",
    "prepare_extend_run",
    "prepare_staged_extension_publish",
]
