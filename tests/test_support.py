import io
import os
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

_FAKE_AGE_SCRIPT = """#!/usr/bin/env python3
import sys


def _find_arg(flag):
    if flag in sys.argv:
        idx = sys.argv.index(flag)
        return sys.argv[idx + 1]
    return None


def main():
    args = sys.argv[1:]
    output_path = _find_arg("-o")
    input_path = args[-1] if args else None

    if "-d" in args:
        sys.stderr.write("Enter passphrase: ")
        sys.stderr.flush()
        _ = sys.stdin.readline()

    if "-p" in args and "-d" not in args:
        sys.stderr.write("Enter passphrase: ")
        sys.stderr.flush()
        _ = sys.stdin.readline()

    if output_path and input_path:
        with open(input_path, "rb") as src, open(output_path, "wb") as dst:
            dst.write(src.read())
    else:
        data = sys.stdin.buffer.read()
        sys.stdout.buffer.write(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""


def write_fake_age_script(directory: Path) -> Path:
    path = directory / "age"
    path.write_text(_FAKE_AGE_SCRIPT, encoding="utf-8")
    os.chmod(path, 0o755)
    return path


@contextmanager
def temp_env(overrides: dict[str, str], *, clear: bool = False):
    with mock.patch.dict(os.environ, overrides, clear=clear):
        yield


@contextmanager
def with_age_path(age_path: Path):
    with temp_env({"ETHERNITY_AGE_PATH": str(age_path)}):
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
def prepend_path(directory: Path):
    previous = os.environ.get("PATH", "")
    os.environ["PATH"] = f"{directory}{os.pathsep}{previous}"
    try:
        yield
    finally:
        os.environ["PATH"] = previous


@contextmanager
def suppress_output():
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        yield
