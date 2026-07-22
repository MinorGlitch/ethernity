"""Deterministic presentation fixtures used by TUI visual tests.

These fixtures deliberately contain no task-domain objects. They make presentation lifecycle
states reproducible without invoking parsers, cryptography, the filesystem, or task execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

StepStatus = Literal["locked", "available", "current", "complete", "warning", "error"]
ViewKind = Literal["workflow", "review", "running", "result"]
NoticeTone = Literal["neutral", "warning", "error", "success"]


@dataclass(frozen=True)
class StepFixture:
    """One stable step row in a visual presentation fixture."""

    title: str
    status: StepStatus
    summary: str


@dataclass(frozen=True)
class RestorePresentationFixture:
    """A complete, deterministic Restore screen presentation state."""

    key: str
    view: ViewKind
    progress: str
    status_label: str
    steps: tuple[StepFixture, ...]
    heading: str
    body: tuple[str, ...]
    notice: str | None
    notice_tone: NoticeTone
    primary_label: str
    primary_enabled: bool
    focus_id: str | None


def _step(title: str, status: StepStatus, summary: str) -> StepFixture:
    return StepFixture(title=title, status=status, summary=summary)


RESTORE_PRESENTATION_STATES: dict[str, RestorePresentationFixture] = {
    "empty": RestorePresentationFixture(
        key="empty",
        view="workflow",
        progress="Step 1 of 4",
        status_label="Not started",
        steps=(
            _step("Load source", "current", "Choose scanned pages, text, or payload files"),
            _step("Unlock", "locked", "Available after the source is understood"),
            _step("Destination", "locked", "Available after unlock"),
            _step("Review", "locked", "Nothing will be written before review"),
        ),
        heading="Load backup material",
        body=(
            "Use the material you would have during an offline recovery.",
            "No source selected",
        ),
        notice=None,
        notice_tone="neutral",
        primary_label="Continue",
        primary_enabled=False,
        focus_id="source-pages",
    ),
    "partial": RestorePresentationFixture(
        key="partial",
        view="workflow",
        progress="Step 2 of 4",
        status_label="In progress",
        steps=(
            _step("Load source", "complete", "3 scanned recovery sheets"),
            _step("Unlock", "current", "Choose one available method"),
            _step("Destination", "available", "Restore to a new folder"),
            _step("Review", "locked", "Unlock method is still required"),
        ),
        heading="Choose an unlock method",
        body=(
            "Passphrase  [selected]",
            "Recovery sheets",
            "Signing key",
            "The passphrase is requested in a private dialog and is never shown here.",
        ),
        notice=None,
        notice_tone="neutral",
        primary_label="Continue",
        primary_enabled=True,
        focus_id="change-unlock",
    ),
    "ready": RestorePresentationFixture(
        key="ready",
        view="review",
        progress="4 of 4 complete",
        status_label="Ready to review",
        steps=(
            _step("Load source", "complete", "3 scanned recovery sheets"),
            _step("Unlock", "complete", "Passphrase"),
            _step("Destination", "complete", "New folder: restored-archive"),
            _step("Review", "current", "Confirm before writing files"),
        ),
        heading="Review restore",
        body=(
            "Source       3 scanned recovery sheets",
            "Backup      8d44...f129",
            "Destination ~/Documents/restored-archive",
            "Conflicts    Stop before replacing an existing file",
        ),
        notice="Authentication and the expected backup fingerprint will be checked.",
        notice_tone="neutral",
        primary_label="Restore files",
        primary_enabled=True,
        focus_id="primary-action",
    ),
    "warning": RestorePresentationFixture(
        key="warning",
        view="review",
        progress="4 of 4 complete",
        status_label="Decision required",
        steps=(
            _step("Load source", "complete", "Backup folder"),
            _step("Unlock", "complete", "Signing key"),
            _step("Destination", "warning", "Existing folder selected"),
            _step("Review", "current", "Confirm the conflict policy"),
        ),
        heading="Review restore",
        body=(
            "Source       ~/Backups/backup-8d44f129",
            "Backup      8d44...f129",
            "Destination ~/Documents/archive",
            "Conflicts    Keep existing files and report skipped paths",
        ),
        notice=(
            "The destination already exists. Existing files will be kept; conflicting restored "
            "files will be skipped."
        ),
        notice_tone="warning",
        primary_label="Restore and keep existing files",
        primary_enabled=True,
        focus_id="primary-action",
    ),
    "error": RestorePresentationFixture(
        key="error",
        view="workflow",
        progress="Step 1 of 4",
        status_label="Source needs attention",
        steps=(
            _step("Load source", "error", "The selected PDF has no recovery payloads"),
            _step("Unlock", "locked", "Available after the source is understood"),
            _step("Destination", "locked", "Available after unlock"),
            _step("Review", "locked", "Resolve the source error first"),
        ),
        heading="Load backup material",
        body=(
            "Selected: family-archive.pdf",
            "Choose another file or paste the recovery text printed below the QR code.",
        ),
        notice="No Ethernity recovery payload was found in family-archive.pdf.",
        notice_tone="error",
        primary_label="Continue",
        primary_enabled=False,
        focus_id="source-pages",
    ),
    "running": RestorePresentationFixture(
        key="running",
        view="running",
        progress="Writing files",
        status_label="Restore in progress",
        steps=(
            _step("Load source", "complete", "3 scanned recovery sheets"),
            _step("Unlock", "complete", "Passphrase"),
            _step("Destination", "complete", "New folder: restored-archive"),
            _step("Review", "complete", "Restore confirmed"),
        ),
        heading="Restoring files",
        body=(
            "Authenticating backup chain                       Complete",
            "Decrypting archive                               Complete",
            "Writing restored files                           In progress",
            "[=======================>------------]  68%",
        ),
        notice="Keep Ethernity open until the destination is finalized.",
        notice_tone="neutral",
        primary_label="Restoring...",
        primary_enabled=False,
        focus_id=None,
    ),
    "success": RestorePresentationFixture(
        key="success",
        view="result",
        progress="Complete",
        status_label="Restore succeeded",
        steps=(
            _step("Load source", "complete", "3 scanned recovery sheets"),
            _step("Unlock", "complete", "Passphrase"),
            _step("Destination", "complete", "New folder: restored-archive"),
            _step("Review", "complete", "12 files restored"),
        ),
        heading="Files restored",
        body=(
            "12 files written",
            "~/Documents/restored-archive",
            "Next: open a few important files before putting the recovery sheets away.",
        ),
        notice="Backup authentication and fingerprint checks passed.",
        notice_tone="success",
        primary_label="Close",
        primary_enabled=True,
        focus_id="primary-action",
    ),
    "failure": RestorePresentationFixture(
        key="failure",
        view="result",
        progress="Stopped",
        status_label="Restore failed",
        steps=(
            _step("Load source", "complete", "3 scanned recovery sheets"),
            _step("Unlock", "complete", "Passphrase"),
            _step("Destination", "error", "Could not create the destination"),
            _step("Review", "complete", "Inputs retained for retry"),
        ),
        heading="Restore could not finish",
        body=(
            "No restored files were committed.",
            "Return to Destination and choose a writable folder, then retry.",
            "Technical details are available from Diagnostics.",
        ),
        notice="Permission was denied while creating ~/Documents/restored-archive.",
        notice_tone="error",
        primary_label="Return to destination",
        primary_enabled=True,
        focus_id="primary-action",
    ),
}


RESTORE_PRESENTATION_STATE_KEYS = (
    "empty",
    "partial",
    "ready",
    "warning",
    "error",
    "running",
    "success",
    "failure",
)
