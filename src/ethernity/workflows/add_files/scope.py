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

"""Load selected files and calculate Add Files changes."""

from __future__ import annotations

from collections.abc import Sequence

from ethernity.extensions.chain import ReconstructedFile
from ethernity.workflows.add_files.request import AddFilesRequest
from ethernity.workflows.shared.input_scope import (
    InputScopeDiff,
    SelectedInputScope,
    load_input_scope,
    summarize_input_scope_diff,
)


def load_selected_scope(request: AddFilesRequest) -> SelectedInputScope | None:
    """Load explicitly selected content without interpreting backup filenames."""

    return load_input_scope(
        raw_files=request.input_paths,
        raw_directories=request.input_directories,
        base_dir_arg=request.base_directory,
        allow_stdin=True,
    )


def summarize_scope_diff(
    current_state: Sequence[ReconstructedFile],
    scope: SelectedInputScope,
) -> InputScopeDiff:
    """Compare the selected local scope against the current reconstructed files."""

    return summarize_input_scope_diff(
        current_files={item.path: (item.data, item.mtime) for item in current_state},
        scope=scope,
    )


__all__ = [
    "load_selected_scope",
    "summarize_scope_diff",
]
