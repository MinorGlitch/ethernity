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

"""Config loaders and installers."""

from .installer import (
    DEFAULT_KIT_TEMPLATE_PATH,
    DEFAULT_PAPER_SIZE,
    DEFAULT_RECOVERY_TEMPLATE_PATH,
    DEFAULT_SHARD_TEMPLATE_PATH,
    DEFAULT_SIGNING_KEY_SHARD_TEMPLATE_PATH,
    DEFAULT_TEMPLATE_PATH,
    DEFAULT_TEMPLATE_STYLE,
    init_user_config,
    list_template_designs,
    resolve_config_path,
    resolve_template_design_path,
    user_config_needs_init,
)
from .loader import (
    AppConfig,
    BackupDefaults,
    CliDefaults,
    DebugDefaults,
    RecoverDefaults,
    RuntimeDefaults,
    UiDefaults,
    apply_template_design,
    build_qr_config,
    load_app_config,
    load_cli_defaults,
)

__all__ = [
    "AppConfig",
    "BackupDefaults",
    "CliDefaults",
    "DEFAULT_KIT_TEMPLATE_PATH",
    "DEFAULT_PAPER_SIZE",
    "DEFAULT_RECOVERY_TEMPLATE_PATH",
    "DEFAULT_SHARD_TEMPLATE_PATH",
    "DEFAULT_SIGNING_KEY_SHARD_TEMPLATE_PATH",
    "DEFAULT_TEMPLATE_PATH",
    "DEFAULT_TEMPLATE_STYLE",
    "DebugDefaults",
    "RecoverDefaults",
    "RuntimeDefaults",
    "UiDefaults",
    "apply_template_design",
    "build_qr_config",
    "init_user_config",
    "list_template_designs",
    "load_app_config",
    "load_cli_defaults",
    "resolve_config_path",
    "resolve_template_design_path",
    "user_config_needs_init",
]
