#!/usr/bin/env python3
# ruff: noqa: E402

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tooling.document_inspector_app import (
    DND_FILES,
    MODE_AUTO,
    MODE_FALLBACK,
    MODE_PAYLOADS,
    REPO_ROOT,
    SRC_ROOT,
    BatchReportEntry,
    FileRecord,
    FrameRecord,
    InspectionResult,
    InspectorApp,
    RecoveredSecretRecord,
    TkinterDnD,
    _collect_scan_files,
    _payload_text_from_clipboard_image,
    _payload_text_from_scan_paths,
    batch_entry_from_result,
    build_batch_report,
    inspect_pasted_text,
    main,
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


if __name__ == "__main__":
    raise SystemExit(main())
