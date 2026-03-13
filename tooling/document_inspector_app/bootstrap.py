from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional local dev dependency
    DND_FILES = None
    TkinterDnD = None

__all__ = ["DND_FILES", "REPO_ROOT", "SRC_ROOT", "TkinterDnD"]
