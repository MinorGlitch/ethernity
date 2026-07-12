from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def single_output_folder(paths: tuple[Path, ...]) -> Path | None:
    parents = {path.parent for path in paths}
    if len(parents) == 1:
        return next(iter(parents))
    try:
        common = Path(os.path.commonpath(tuple(str(parent) for parent in parents)))
    except ValueError:
        return None
    if str(common) in {"", "."} or common == Path(common.anchor):
        return None
    return common


def common_output_folder(paths: tuple[Path, ...]) -> str:
    folder = single_output_folder(paths)
    if folder is not None:
        return str(folder)
    return "Multiple output folders"


def open_folder(folder: Path) -> None:
    command = ["open", str(folder)]
    if sys.platform.startswith("win"):
        command = ["explorer", str(folder)]
    elif sys.platform != "darwin":
        command = ["xdg-open", str(folder)]
    subprocess.Popen(command)  # noqa: S603
