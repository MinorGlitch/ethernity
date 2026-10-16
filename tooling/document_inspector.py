#!/usr/bin/env python3

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_app = import_module("tooling.document_inspector_app")

BatchReportEntry = _app.BatchReportEntry
DND_FILES = _app.DND_FILES
FileRecord = _app.FileRecord
FrameRecord = _app.FrameRecord
InspectionResult = _app.InspectionResult
InspectorApp = _app.InspectorApp
MODE_AUTO = _app.MODE_AUTO
MODE_FALLBACK = _app.MODE_FALLBACK
MODE_PAYLOADS = _app.MODE_PAYLOADS
REPO_ROOT = _app.REPO_ROOT
RecoveredSecretRecord = _app.RecoveredSecretRecord
SRC_ROOT = _app.SRC_ROOT
TkinterDnD = _app.TkinterDnD
_collect_scan_files = _app._collect_scan_files
_payload_text_from_clipboard_image = _app._payload_text_from_clipboard_image
_payload_text_from_scan_paths = _app._payload_text_from_scan_paths
batch_entry_from_result = _app.batch_entry_from_result
build_batch_report = _app.build_batch_report
inspect_pasted_text = _app.inspect_pasted_text
main = _app.main

__all__ = _app.__all__

if __name__ == "__main__":
    raise SystemExit(main())
