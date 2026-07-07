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

# =============================================================================
# Environment Helpers
# =============================================================================


@contextmanager
def temp_env(overrides: dict[str, str], *, clear: bool = False):
    with mock.patch.dict(os.environ, overrides, clear=clear):
        yield


def build_cli_env(*, overrides: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    if overrides:
        env.update(overrides)
    return env


def cli_subprocess_timeout_seconds() -> float:
    raw = os.environ.get("ETHERNITY_TEST_CLI_TIMEOUT_SECONDS")
    if raw is None:
        return 300.0
    try:
        timeout = float(raw)
    except ValueError:
        return 300.0
    return timeout if timeout > 0 else 300.0


@contextmanager
def suppress_output():
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        yield
