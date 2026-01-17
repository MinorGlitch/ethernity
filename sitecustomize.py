import sys
from pathlib import Path

# Ensure the src layout is importable when running from the repo root.
SRC_ROOT = Path(__file__).resolve().parent / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
