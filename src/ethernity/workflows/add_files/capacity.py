"""Require newly published extension states to remain rebuildable."""

from __future__ import annotations

from ethernity.extensions.build import VerifiedExtensionCandidate
from ethernity.extensions.recovery import (
    RECONSTRUCTED_STATE_INPUT_ORIGIN,
    RECONSTRUCTED_STATE_INPUT_ROOTS,
)
from ethernity.formats.manifest import BackupFile
from ethernity.workflows.add_files.errors import AddFilesWorkflowError
from ethernity.workflows.add_files.models import PreparedAddFilesRun
from ethernity.workflows.shared import api_codes, standalone


def require_rebuildable_result(
    prepared: PreparedAddFilesRun,
    candidate: VerifiedExtensionCandidate,
) -> int:
    """Validate the merged state without restricting recovery of existing chains."""

    parts = tuple(
        BackupFile(path=item.path, data=item.data, mtime=item.mtime)
        for item in candidate.resulting_state
    )
    try:
        return standalone.require_standalone_capacity(
            parts,
            signing_seed=prepared.signing_seed,
            passphrase=prepared.encryption_passphrase,
            input_origin=RECONSTRUCTED_STATE_INPUT_ORIGIN,
            input_roots=RECONSTRUCTED_STATE_INPUT_ROOTS,
        )
    except ValueError as exc:
        raise AddFilesWorkflowError(
            code=api_codes.ADD_FILES_NOT_REBUILDABLE,
            message=(
                "The updated backup cannot fit a standalone Rebuild backup. "
                "Select fewer new files, use smaller replacements, or create a separate backup."
            ),
            details={"stage": "rebuild_capacity", "constraint": str(exc)},
        ) from exc


__all__ = ["require_rebuildable_result"]
