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

"""Public CLI prompt surface (prompt primitives + path pickers)."""

from __future__ import annotations

from ethernity.cli.shared.ui.picker import (
    prompt_optional_path,
    prompt_optional_path_with_picker,
    prompt_path_with_picker,
    prompt_paths_with_picker,
    prompt_required_path,
    prompt_required_paths,
    prompt_select_path,
    prompt_select_paths,
    validate_path,
)
from ethernity.cli.shared.ui.prompts_core import (
    print_prompt_header,
    prompt_choice,
    prompt_choice_list,
    prompt_int,
    prompt_multiline,
    prompt_optional,
    prompt_optional_secret,
    prompt_required,
    prompt_required_secret,
    prompt_yes_no,
)

__all__ = [
    "print_prompt_header",
    "prompt_choice",
    "prompt_choice_list",
    "prompt_int",
    "prompt_multiline",
    "prompt_optional",
    "prompt_optional_path",
    "prompt_optional_path_with_picker",
    "prompt_optional_secret",
    "prompt_path_with_picker",
    "prompt_paths_with_picker",
    "prompt_required",
    "prompt_required_path",
    "prompt_required_paths",
    "prompt_required_secret",
    "prompt_select_path",
    "prompt_select_paths",
    "prompt_yes_no",
    "validate_path",
]
