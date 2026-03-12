from __future__ import annotations

from .analysis import batch_entry_from_result, build_batch_report, inspect_pasted_text
from .bootstrap import DND_FILES, REPO_ROOT, SRC_ROOT, TkinterDnD
from .constants import MODE_AUTO, MODE_FALLBACK, MODE_PAYLOADS
from .gui import InspectorApp, main
from .models import (
    BatchReportEntry,
    FileRecord,
    FrameRecord,
    InspectionResult,
    RecoveredSecretRecord,
)
from .scan_sources import (
    _collect_scan_files,
    _payload_text_from_clipboard_image,
    _payload_text_from_scan_paths,
)

__all__ = [
    "BatchReportEntry",
    "DND_FILES",
    "FileRecord",
    "FrameRecord",
    "InspectionResult",
    "InspectorApp",
    "MODE_AUTO",
    "MODE_FALLBACK",
    "MODE_PAYLOADS",
    "REPO_ROOT",
    "RecoveredSecretRecord",
    "SRC_ROOT",
    "TkinterDnD",
    "_collect_scan_files",
    "_payload_text_from_clipboard_image",
    "_payload_text_from_scan_paths",
    "batch_entry_from_result",
    "build_batch_report",
    "inspect_pasted_text",
    "main",
]
