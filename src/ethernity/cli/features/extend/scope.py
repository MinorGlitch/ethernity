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

"""Selected-scope loading and diff helpers for extension planning."""

from __future__ import annotations

from collections.abc import Sequence

from ethernity.cli.shared.input_scope import (
    InputScopeDiff,
    SelectedInputScope,
    empty_scope_inspection_payload,
    load_input_scope,
    summarize_input_scope_diff,
)
from ethernity.cli.shared.types import ExtendArgs
from ethernity.extensions.chain import LogicalFileState

SelectedExtendScope = SelectedInputScope
ExtendScopeDiff = InputScopeDiff


def load_selected_scope(args: ExtendArgs) -> SelectedExtendScope | None:
    """Load validated selected-scope inputs from extend arguments."""

    return load_input_scope(
        raw_files=args.input or (),
        raw_directories=args.input_dir or (),
        base_dir_arg=args.base_dir,
        allow_stdin=True,
    )


def summarize_scope_diff(
    current_state: Sequence[LogicalFileState],
    scope: SelectedExtendScope,
) -> ExtendScopeDiff:
    """Compare the selected local scope against the current logical chain state."""

    return summarize_input_scope_diff(
        current_files={item.path: (item.data, item.mtime) for item in current_state},
        scope=scope,
    )


__all__ = [
    "ExtendScopeDiff",
    "SelectedExtendScope",
    "empty_scope_inspection_payload",
    "load_selected_scope",
    "summarize_scope_diff",
]
