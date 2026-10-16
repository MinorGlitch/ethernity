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

"""Root selection shared by best-effort inspection and strict recovery planning."""

from __future__ import annotations

from collections.abc import Callable

from ethernity.encoding.framing import Frame
from ethernity.extensions.errors import OrphanAuthFramesError
from ethernity.extensions.recovery import (
    ImportedRecoveryDocument,
    imported_documents_from_recovery_frames,
    select_root_import_session,
)
from ethernity.workflows.recovery.inspection import (
    select_root_import_document_from_passphrase_shards,
)
from ethernity.workflows.recovery.models import RecoveryRootSelection
from ethernity.workflows.shared.notices import WorkflowNoticeSink


def import_recovery_documents(
    frames: list[Frame],
    extra_auth_frames: list[Frame],
    *,
    source_label: str,
) -> tuple[ImportedRecoveryDocument, ...]:
    """Import carriers while leaving single-document AUTH errors to authentication."""
    try:
        return imported_documents_from_recovery_frames(
            [*frames, *extra_auth_frames],
            source_label=source_label,
        )
    except OrphanAuthFramesError:
        documents = imported_documents_from_recovery_frames(frames, source_label=source_label)
        if len(documents) > 1:
            raise
        return documents


def select_recovery_root(
    documents: tuple[ImportedRecoveryDocument, ...],
    *,
    frames: list[Frame],
    extra_auth_frames: list[Frame],
    shard_frames: list[Frame],
    passphrase: str | None,
    allow_unsigned: bool,
    passphrase_fallback: Callable[[], str] | None = None,
    notice_sink: WorkflowNoticeSink | None = None,
) -> RecoveryRootSelection:
    """Select once, preserving the decoded session for later chain recovery.

    Selection errors propagate to the caller, which decides whether to report blockers
    or abort. A single document follows ordinary authentication and unlock checks.
    """
    if len(documents) <= 1:
        return RecoveryRootSelection(
            frames=tuple(frames),
            extra_auth_frames=tuple(extra_auth_frames),
            shard_frames=tuple(shard_frames),
            passphrase=passphrase,
        )

    shard_unlock = None
    if not passphrase and shard_frames:
        selection = select_root_import_document_from_passphrase_shards(
            documents,
            shard_frames=shard_frames,
            allow_unsigned=allow_unsigned,
            _notice_sink=notice_sink,
        )
        root = selection.root_document
        shard_unlock = selection.unlock
        passphrase = shard_unlock.resolved_passphrase
        decoded_session = selection.decoded_import_session
    else:
        if not passphrase:
            if passphrase_fallback is None:
                raise ValueError(
                    "passphrase is required when recovery input contains multiple MAIN documents"
                )
            passphrase = passphrase_fallback()
        decoded_session = select_root_import_session(documents, passphrase=passphrase, debug=False)
        root = decoded_session.root_document

    return RecoveryRootSelection(
        frames=tuple(frame for frame in frames if frame.doc_id == root.doc_id),
        extra_auth_frames=tuple(
            frame for frame in extra_auth_frames if frame.doc_id == root.doc_id
        ),
        shard_frames=() if shard_unlock is not None else tuple(shard_frames),
        passphrase=passphrase,
        shard_unlock=shard_unlock,
        decoded_import_session=decoded_session,
    )
