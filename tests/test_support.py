import io
import os
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from unittest import mock


@contextmanager
def temp_env(overrides: dict[str, str], *, clear: bool = False):
    with mock.patch.dict(os.environ, overrides, clear=clear):
        yield


@contextmanager
def with_playwright_skip():
    with temp_env({"ETHERNITY_SKIP_PLAYWRIGHT_INSTALL": "1"}):
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


@contextmanager
def suppress_output():
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        yield
