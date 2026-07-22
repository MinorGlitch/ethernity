#!/usr/bin/env python3
# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>.

"""CLI compatibility adapter for neutral input-file loading."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Literal, cast

from rich.progress import Progress

from ethernity.core.bounds import MAX_DECOMPRESSED_PAYLOAD_BYTES, MAX_MANIFEST_FILES
from ethernity.core.validation import normalize_path
from ethernity.workflows.shared import file_inputs as _file_inputs
from ethernity.workflows.shared.file_inputs import (
    InputFile,
    InputLoadProgress,
    directory_root_label,
    load_input_files as _load_input_files,
)

_directory_root_label = directory_root_label
_read_planned_input_file = _file_inputs._read_planned_input_file


def _synchronize_compatibility_overrides() -> None:
    """Honor existing callers that replace legacy module-level input hooks."""

    _file_inputs.os = os
    _file_inputs.sys = sys
    _file_inputs.MAX_DECOMPRESSED_PAYLOAD_BYTES = MAX_DECOMPRESSED_PAYLOAD_BYTES
    _file_inputs.MAX_MANIFEST_FILES = MAX_MANIFEST_FILES
    _file_inputs._read_planned_input_file = _read_planned_input_file
    _file_inputs.normalize_path = normalize_path


def load_input_files(
    input_paths: list[str],
    input_dirs: list[str],
    base_dir: str | None,
    *,
    allow_stdin: bool,
    progress: Progress | None = None,
) -> tuple[list[InputFile], Path | None, Literal["file", "directory", "mixed"], list[str]]:
    """Load input files while preserving the established CLI progress surface."""

    _synchronize_compatibility_overrides()
    return _load_input_files(
        input_paths,
        input_dirs,
        base_dir,
        allow_stdin=allow_stdin,
        progress=cast(InputLoadProgress | None, progress),
    )


__all__ = ["load_input_files"]
