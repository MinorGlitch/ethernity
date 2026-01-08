#!/usr/bin/env python3
from __future__ import annotations

from collections.abc import Callable
import functools
from pathlib import Path
import inspect
import importlib.metadata
import os
import re
import subprocess
import sys

import playwright
from playwright.sync_api import sync_playwright
from platformdirs import user_cache_dir
from rich.traceback import install as install_rich_traceback

from .api import console, _configure_ui, _progress
from ..config import init_user_config, user_config_needs_init
from ..crypto.age_cli import ensure_age_binary

_AGE_SKIP_ENV = "ETHERNITY_SKIP_AGE_INSTALL"
_PLAYWRIGHT_SKIP_ENV = "ETHERNITY_SKIP_PLAYWRIGHT_INSTALL"
_PLAYWRIGHT_BROWSERS_ENV = "PLAYWRIGHT_BROWSERS_PATH"
_PLAYWRIGHT_PERCENT_RE = re.compile(r"(\\d{1,3})%")

ProgressCallback = Callable[[int | None, int | None, str | None], None]


def run_startup(
    *,
    quiet: bool,
    no_color: bool,
    no_animations: bool,
    debug: bool,
    init_config: bool,
) -> bool:
    _configure_ui(no_color=no_color, no_animations=no_animations)
    if debug:
        install_rich_traceback(show_locals=True)
    _ensure_age_binary(quiet=quiet)
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


def _configure_playwright_env() -> None:
    if os.environ.get(_PLAYWRIGHT_BROWSERS_ENV):
        return
    cache_dir = user_cache_dir("ms-playwright", appauthor=False)
    os.environ[_PLAYWRIGHT_BROWSERS_ENV] = cache_dir


def _playwright_chromium_installed() -> bool:
    try:
        with sync_playwright() as playwright_instance:
            executable = Path(playwright_instance.chromium.executable_path)
    except Exception:
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
    progress,
    task_id: int,
    completed: int | None,
    total: int | None,
    description: str | None,
) -> None:
    if total is not None:
        progress.update(task_id, total=total)
    if description:
        progress.update(task_id, description=description)
    if completed is not None:
        progress.update(task_id, completed=completed)


def _progress_finalize(progress, task_id: int) -> None:
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
    with _progress(quiet=quiet) as progress:
        task_id = None
        if progress is not None:
            task_id = progress.add_task(description, total=None)
        progress_cb = (
            functools.partial(_progress_update, progress, task_id) if progress else None
        )
        ensure(progress_cb)
        if progress is not None and task_id is not None:
            _progress_finalize(progress, task_id)


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
    assert process.stdout is not None
    for line in process.stdout:
        output_lines.append(line)
        if len(output_lines) > 200:
            output_lines.pop(0)
        percent, description = _parse_playwright_progress(line)
        if percent is not None:
            current = max(current, percent)
        if description:
            progress_cb(current if current else None, 100, description)
        elif percent is not None:
            progress_cb(current, 100, None)
    returncode = process.wait()
    if returncode != 0:
        detail = "".join(output_lines).strip() or "unknown error"
        raise RuntimeError(f"Playwright install failed: {detail}")


def _ensure_age_binary(*, quiet: bool) -> None:
    _ensure_dependency(
        quiet=quiet,
        skip_env=_AGE_SKIP_ENV,
        description="Initializing age binary...",
        ensure=ensure_age_binary,
    )


def _parse_playwright_progress(line: str) -> tuple[int | None, str | None]:
    stripped = line.strip()
    percent = None
    match = _PLAYWRIGHT_PERCENT_RE.search(stripped)
    if match:
        try:
            percent = int(match.group(1))
        except ValueError:
            percent = None
    description = None
    if stripped.startswith(("Downloading", "Installing", "Extracting")):
        description = stripped
    return percent, description
