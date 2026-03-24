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

from __future__ import annotations

from ethernity.cli.shared.ui.home import (
    HOME_BANNER,
    empty_mint_args,
    empty_recover_args,
    prompt_home_action,
    render_home_banner,
)
from ethernity.cli.shared.ui.prompts import (
    print_prompt_header,
    prompt_choice,
    prompt_choice_list,
    prompt_int,
    prompt_multiline,
    prompt_optional,
    prompt_optional_path,
    prompt_optional_path_with_picker,
    prompt_optional_secret,
    prompt_path_with_picker,
    prompt_paths_with_picker,
    prompt_required,
    prompt_required_path,
    prompt_required_paths,
    prompt_required_secret,
    prompt_select_path,
    prompt_select_paths,
    prompt_yes_no,
    validate_path,
)
from ethernity.cli.shared.ui.renderables import (
    build_action_list,
    build_kv_table,
    build_list_table,
    build_outputs_tree,
    build_recovered_tree,
    build_review_table,
    panel,
    print_completion_panel,
)
from ethernity.cli.shared.ui.runtime import (
    DEBUG_MAX_BYTES_DEFAULT,
    THEME,
    configure_ui,
    console,
    console_err,
    progress,
    status,
    ui_screen_mode,
    wizard_flow,
    wizard_stage,
)
from ethernity.cli.shared.ui.state import WizardState, format_hint

__all__ = [
    "DEBUG_MAX_BYTES_DEFAULT",
    "HOME_BANNER",
    "THEME",
    "WizardState",
    "build_action_list",
    "build_kv_table",
    "build_list_table",
    "build_outputs_tree",
    "build_recovered_tree",
    "build_review_table",
    "configure_ui",
    "console",
    "console_err",
    "empty_mint_args",
    "empty_recover_args",
    "format_hint",
    "panel",
    "print_completion_panel",
    "print_prompt_header",
    "progress",
    "prompt_choice",
    "prompt_choice_list",
    "prompt_home_action",
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
    "ui_screen_mode",
    "status",
    "render_home_banner",
    "validate_path",
    "wizard_flow",
    "wizard_stage",
]
