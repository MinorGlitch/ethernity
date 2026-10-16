from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SourceKind = Literal[
    "backup_folder", "scanned_pages", "recovery_text", "payload_files", "recovery_inputs"
]


@dataclass(frozen=True, slots=True)
class SourceDescription:
    """Identity and version of an assessed source, shared with its presentation."""

    source_kind: SourceKind
    source_label: str
    source_summary: str
    backup_identity: str = ""
    version_summary: str = ""
