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

import io
import os
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from unittest import mock

from ethernity.cli.bootstrap.startup import (
    ensure_playwright_browsers as _ensure_playwright_browsers,
)

# =============================================================================
# Environment Helpers
# =============================================================================


@contextmanager
def temp_env(overrides: dict[str, str], *, clear: bool = False):
    with mock.patch.dict(os.environ, overrides, clear=clear):
        yield


def build_cli_env(
    *, overrides: dict[str, str] | None = None, skip_playwright: bool = True
) -> dict[str, str]:
    env = os.environ.copy()
    if skip_playwright:
        env["ETHERNITY_SKIP_PLAYWRIGHT_INSTALL"] = "1"
    if overrides:
        env.update(overrides)
    return env


def ensure_playwright_browsers() -> None:
    os.environ.pop("ETHERNITY_SKIP_PLAYWRIGHT_INSTALL", None)
    _ensure_playwright_browsers(quiet=True)


@contextmanager
def suppress_output():
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        yield
