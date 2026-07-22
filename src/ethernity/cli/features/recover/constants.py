"""Shared recovery labels that do not depend on interactive input code."""

from __future__ import annotations

RECOVERY_TEXT_LABEL = "Recovery text"
RECOVERY_QR_TEXT_LABEL = "Backup text lines"
RECOVERY_SCAN_LABEL = "Backup PDF or images"

__all__ = [
    "RECOVERY_QR_TEXT_LABEL",
    "RECOVERY_SCAN_LABEL",
    "RECOVERY_TEXT_LABEL",
]
