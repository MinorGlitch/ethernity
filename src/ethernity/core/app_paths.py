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

"""Centralized app-owned filesystem paths."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from platformdirs import user_cache_dir, user_config_dir, user_log_dir, user_state_dir

APP_NAME = "ethernity"
PLAYWRIGHT_CACHE_APP_NAME = "ms-playwright"
XDG_CONFIG_ENV = "XDG_CONFIG_HOME"
DEFAULT_CONFIG_FILENAME = "config.toml"
TEMPLATES_DIRNAME = "templates"
RUNTIME_DIRNAME = "runtime"


def user_config_dir_path() -> Path:
    """Return the effective user config directory for Ethernity."""

    xdg_override = os.environ.get(XDG_CONFIG_ENV)
    if xdg_override:
        return Path(xdg_override).expanduser() / APP_NAME
    if sys.platform == "darwin":
        # Keep the existing ~/.config policy for compatibility across v1 docs/tests.
        return Path.home() / ".config" / APP_NAME
    return Path(user_config_dir(APP_NAME, appauthor=False))


def user_config_file_path(filename: str = DEFAULT_CONFIG_FILENAME) -> Path:
    """Return the user config file path under the app config directory."""

    return user_config_dir_path() / filename


def user_templates_root_path() -> Path:
    """Return the user templates root directory under app config."""

    return user_config_dir_path() / TEMPLATES_DIRNAME


def user_templates_design_path(design: str) -> Path:
    """Return the user override directory for a template design."""

    return user_templates_root_path() / design


def user_cache_dir_path() -> Path:
    """Return the app-owned cache directory."""

    return Path(user_cache_dir(APP_NAME, appauthor=False))


def playwright_browsers_cache_dir() -> Path:
    """Return the Playwright browser cache directory used by the CLI."""

    return Path(user_cache_dir(PLAYWRIGHT_CACHE_APP_NAME, appauthor=False))


def user_state_dir_path() -> Path:
    """Return the app-owned state directory."""

    return Path(user_state_dir(APP_NAME, appauthor=False))


def user_log_dir_path() -> Path:
    """Return the app-owned log directory."""

    return Path(user_log_dir(APP_NAME, appauthor=False))


def runtime_scratch_dir_path() -> Path:
    """Return the app-owned runtime scratch directory (under cache)."""

    return user_cache_dir_path() / RUNTIME_DIRNAME
