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

"""Preparation helpers for extend execution."""

from __future__ import annotations

from typing import cast

from ethernity.cli.features.extend.models import (
    EXTENSION_INPUT_REQUIRED,
    EXTENSION_NO_CHANGES,
    EncryptedPreparedExtension,
    PreparedExtendRun,
    PreparedExtensionPublishPlan,
)
from ethernity.cli.features.extend.planning import ResolvedExtendState, resolve_extend_state
from ethernity.cli.shared.crypto import _doc_id_and_hash_from_ciphertext
from ethernity.cli.shared.ndjson import ApiCommandError
from ethernity.cli.shared.types import ExtendArgs
from ethernity.crypto import encrypt_bytes_with_passphrase
from ethernity.extensions.build import Chunker, build_extension_document, build_virtual_chunk_source
from ethernity.extensions.staging import (
    ExtensionPublishPolicy,
    create_staged_extension_artifact_plan,
)


def prepare_extend_run(args: ExtendArgs) -> PreparedExtendRun:
    """Validate extend preconditions and summarize the pending change set."""

    if not args.input and not args.input_dir:
        raise ApiCommandError(
            code=EXTENSION_INPUT_REQUIRED,
            message="extend requires at least one explicit --input or --input-dir selection",
        )

    return prepare_extend_run_from_state(args, resolve_extend_state(args))


def prepare_extend_run_from_state(
    args: ExtendArgs,
    resolved: ResolvedExtendState,
) -> PreparedExtendRun:
    """Validate extend preconditions from an already resolved planning state."""

    if not args.input and not args.input_dir:
        raise ApiCommandError(
            code=EXTENSION_INPUT_REQUIRED,
            message="extend requires at least one explicit --input or --input-dir selection",
        )

    inspection = resolved.inspection
    if inspection.blocking_issues:
        first_issue = inspection.blocking_issues[0]
        raise ApiCommandError(
            code=str(first_issue["code"]),
            message=str(first_issue["message"]),
            details=cast(dict[str, object], first_issue.get("details") or {}),
        )

    if inspection.diff_summary is None:
        raise ApiCommandError(
            code="RUNTIME_ERROR",
            message="extend planning did not produce a diff summary",
        )

    changed_paths = tuple(_read_diff_list(inspection.diff_summary, "changed_paths"))
    new_paths = tuple(_read_diff_list(inspection.diff_summary, "new_paths"))
    unchanged_paths = tuple(_read_diff_list(inspection.diff_summary, "unchanged_paths"))

    if not changed_paths and not new_paths:
        raise ApiCommandError(
            code=EXTENSION_NO_CHANGES,
            message="selected scope matches the current chain state; nothing to extend",
        )

    loaded_scope = resolved.loaded_scope
    if loaded_scope is None:
        raise ApiCommandError(
            code="RUNTIME_ERROR",
            message="extend planning did not retain the selected scope",
        )
    current_state = resolved.current_state
    if current_state is None:
        raise ApiCommandError(
            code="RUNTIME_ERROR",
            message="extend planning did not retain the current chain state",
        )
    if (
        resolved.resolved_passphrase is None
        or not resolved.resolved_passphrase
        or resolved.root_doc_hash is None
        or resolved.parent_doc_hash is None
        or resolved.next_index is None
        or resolved.signing_seed is None
        or resolved.chunking is None
    ):
        raise ApiCommandError(
            code="RUNTIME_ERROR",
            message="extend planning did not resolve chain lineage for execution",
        )

    return PreparedExtendRun(
        args=args,
        inspection=inspection,
        loaded_scope=loaded_scope,
        current_state=current_state,
        encryption_passphrase=resolved.resolved_passphrase,
        root_doc_hash=resolved.root_doc_hash,
        parent_doc_hash=resolved.parent_doc_hash,
        next_index=resolved.next_index,
        signing_seed=resolved.signing_seed,
        chunking=resolved.chunking,
        input_origin=loaded_scope.input_origin,
        input_roots=loaded_scope.input_roots,
        changed_paths=changed_paths,
        new_paths=new_paths,
        unchanged_paths=unchanged_paths,
    )


def _read_diff_list(diff_summary: dict[str, object], key: str) -> tuple[str, ...]:
    raw_value = diff_summary.get(key)
    if raw_value is None:
        return ()
    if not isinstance(raw_value, list):
        raise ApiCommandError(
            code="RUNTIME_ERROR",
            message=f"extend diff summary field {key!r} must be a list",
        )
    return tuple(str(item) for item in raw_value)


def assemble_prepared_extension_document(
    prepared: PreparedExtendRun,
    *,
    chunker: Chunker,
):
    """Assemble an extension envelope from a prepared extend run."""

    selected_paths = set(prepared.changed_paths) | set(prepared.new_paths)
    input_files = tuple(
        item for item in prepared.loaded_scope.input_files if item.relative_path in selected_paths
    )
    if not input_files:
        raise ApiCommandError(
            code=EXTENSION_NO_CHANGES,
            message="extend assembly found no changed input files to encode",
        )

    existing_chunks = build_virtual_chunk_source(
        tuple(item.data for item in prepared.current_state),
        chunking=prepared.chunking,
        chunker=chunker,
    )
    existing_file_sizes = {item.path: item.size for item in prepared.current_state}
    return build_extension_document(
        index=prepared.next_index,
        parent_doc_hash=prepared.parent_doc_hash,
        root_doc_hash=prepared.root_doc_hash,
        chunking=prepared.chunking,
        input_files=input_files,
        input_origin=prepared.input_origin,
        input_roots=prepared.input_roots,
        chunker=chunker,
        existing_chunks=existing_chunks,
        existing_logical_bytes=sum(item.size for item in prepared.current_state),
        existing_file_sizes=existing_file_sizes,
    )


def encrypt_prepared_extension_document(
    prepared: PreparedExtendRun,
    *,
    chunker: Chunker,
) -> EncryptedPreparedExtension:
    """Build and encrypt an extension document using the resolved chain passphrase."""

    built = assemble_prepared_extension_document(prepared, chunker=chunker)
    plaintext = built.document.encode()
    ciphertext, _passphrase = encrypt_bytes_with_passphrase(
        plaintext,
        passphrase=prepared.encryption_passphrase,
    )
    doc_id, doc_hash = _doc_id_and_hash_from_ciphertext(ciphertext)
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

    if not prepared.args.root_dir:
        raise ApiCommandError(
            code="RUNTIME_ERROR",
            message="extend execution requires a root_dir for staged publish planning",
        )

    encrypted = encrypt_prepared_extension_document(prepared, chunker=chunker)
    artifacts = create_staged_extension_artifact_plan(
        prepared.args.root_dir,
        index=prepared.next_index,
        doc_id_hex=encrypted.doc_id.hex(),
        nonce=nonce,
        publish_policy=publish_policy,
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
