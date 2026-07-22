from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

__all__ = ["has_selected_inputs"]


def has_selected_inputs(
    input_paths: Sequence[Path],
    input_dirs: Sequence[Path],
) -> bool:
    return bool(input_paths or input_dirs)
