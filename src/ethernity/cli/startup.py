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

import functools
import importlib.metadata
import inspect
import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import playwright
from platformdirs import user_cache_dir
from playwright.sync_api import sync_playwright
from rich.progress import Progress, TaskID
from rich.traceback import install as install_rich_traceback

from ..config import init_user_config, user_config_needs_init
from .api import configure_ui, console, progress

_PLAYWRIGHT_SKIP_ENV = "ETHERNITY_SKIP_PLAYWRIGHT_INSTALL"
_PLAYWRIGHT_BROWSERS_ENV = "PLAYWRIGHT_BROWSERS_PATH"
_PLAYWRIGHT_PERCENT_RE = re.compile(r"(\d{1,3})%")

ProgressCallback = Callable[[int | None, int | None, str | None], None]


def run_startup(
    *,
    quiet: bool,
    no_color: bool,
    no_animations: bool,
    debug: bool,
    init_config: bool,
) -> bool:
    configure_ui(no_color=no_color, no_animations=no_animations)
    if debug:
        install_rich_traceback(show_locals=True)
    _ensure_playwright_browsers(quiet=quiet)
    if init_config:
        config_dir = init_user_config()
        console.print(f"User config ready at {config_dir}")
        return True
    if user_config_needs_init():
        config_dir = init_user_config()
        if not quiet:
            console.print(f"[dim]Initialized user config at {config_dir}[/dim]")
    return False


def ensure_playwright_browsers(*, quiet: bool = True) -> None:
    _ensure_playwright_browsers(quiet=quiet)


def _configure_playwright_env() -> None:
    if os.environ.get(_PLAYWRIGHT_BROWSERS_ENV):
        return
    cache_dir = user_cache_dir("ms-playwright", appauthor=False)
    os.environ[_PLAYWRIGHT_BROWSERS_ENV] = cache_dir


def _playwright_chromium_installed() -> bool:
    try:
        with sync_playwright() as playwright_instance:
            executable = Path(playwright_instance.chromium.executable_path)
    except (OSError, RuntimeError, playwright.sync_api.Error):
        return False
    return executable.exists()


def _playwright_driver_command() -> tuple[str, str]:
    driver_path = Path(inspect.getfile(playwright)).parent / "driver"
    cli_path = str(driver_path / "package" / "cli.js")
    if sys.platform == "win32":
        node_path = os.getenv("PLAYWRIGHT_NODEJS_PATH", str(driver_path / "node.exe"))
    else:
        node_path = os.getenv("PLAYWRIGHT_NODEJS_PATH", str(driver_path / "node"))
    return node_path, cli_path


def _playwright_driver_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PW_LANG_NAME"] = "python"
    env["PW_LANG_NAME_VERSION"] = f"{sys.version_info.major}.{sys.version_info.minor}"
    env["PW_CLI_DISPLAY_VERSION"] = importlib.metadata.version("playwright")
    return env


def _progress_update(
    progress: Progress,
    task_id: TaskID | None,
    completed: int | None,
    total: int | None,
    description: str | None,
) -> None:
    if task_id is None:
        return
    if total is not None:
        progress.update(task_id, total=total)
    if description:
        progress.update(task_id, description=description)
    if completed is not None:
        progress.update(task_id, completed=completed)


def _progress_finalize(progress: Progress, task_id: TaskID) -> None:
    total = progress.tasks[task_id].total
    if total is not None:
        progress.update(task_id, completed=total)
        return
    completed = progress.tasks[task_id].completed
    if not completed:
        progress.update(task_id, completed=1)


def _ensure_dependency(
    *,
    quiet: bool,
    skip_env: str,
    description: str,
    ensure: Callable[[ProgressCallback | None], None],
    precheck: Callable[[], bool] | None = None,
) -> None:
    if os.environ.get(skip_env):
        return
    if precheck is not None and precheck():
        return
    with progress(quiet=quiet) as progress_bar:
        task_id = None
        if progress_bar is not None:
            task_id = progress_bar.add_task(description, total=None)
        progress_cb = (
            functools.partial(_progress_update, progress_bar, task_id) if progress_bar else None
        )
        ensure(progress_cb)
        if progress_bar is not None and task_id is not None:
            _progress_finalize(progress_bar, task_id)


def _ensure_playwright_browsers(*, quiet: bool) -> None:
    _ensure_dependency(
        quiet=quiet,
        skip_env=_PLAYWRIGHT_SKIP_ENV,
        description="Initializing Playwright (Chromium browser)...",
        ensure=_playwright_install,
        precheck=_playwright_precheck,
    )


def _playwright_precheck() -> bool:
    _configure_playwright_env()
    return _playwright_chromium_installed()


def _playwright_install(progress_cb: ProgressCallback | None) -> None:
    driver_executable, driver_cli = _playwright_driver_command()
    cmd = [driver_executable, driver_cli, "install", "chromium"]
    env = _playwright_driver_env()
    if progress_cb is None:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            check=False,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
            raise RuntimeError(f"Playwright install failed: {detail}")
        return

    output_lines: list[str] = []
    current = 0
    progress_cb(0, 100, None)
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
        bufsize=1,
    )
    if process.stdout is None:
        raise RuntimeError("Playwright install failed: unable to capture output")
    for line in process.stdout:
        output_lines.append(line)
        if len(output_lines) > 200:
            output_lines.pop(0)
        percent = _parse_playwright_progress(line)
        if percent is not None:
            current = max(current, percent)
        else:
            current = min(99, current + 1)
        progress_cb(current, 100, None)
    returncode = process.wait()
    if returncode != 0:
        detail = "".join(output_lines).strip() or "unknown error"
        raise RuntimeError(f"Playwright install failed: {detail}")


def _parse_playwright_progress(line: str) -> int | None:
    stripped = line.strip()
    percent = None
    match = _PLAYWRIGHT_PERCENT_RE.search(stripped)
    if match:
        try:
            percent = int(match.group(1))
        except ValueError:
            percent = None
    return percent
