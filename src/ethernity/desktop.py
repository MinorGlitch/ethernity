"""Browser entry point used by the installed desktop shortcuts."""

from __future__ import annotations

import ctypes
import multiprocessing
import os
import subprocess
import sys
import webbrowser
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from ethernity.app.desktop_tray import run_desktop


@contextmanager
def installer_lock() -> Iterator[None]:
    """Let Windows Setup detect a running desktop app before replacing its files."""
    if sys.platform == "win32":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
        kernel.CreateMutexW.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
        kernel.CloseHandle.restype = ctypes.c_int
        handle = kernel.CreateMutexW(None, False, "Local\\Ethernity.Desktop")
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            yield
        finally:
            kernel.CloseHandle(handle)
    else:
        yield


def show_error(message: str) -> None:
    if sys.platform == "win32":
        dialog = ctypes.windll.user32.MessageBoxW
        dialog.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint)
        dialog.restype = ctypes.c_int
        dialog(None, message, "Ethernity", 0x10)
    elif sys.platform == "darwin":
        subprocess.run(
            [
                "/usr/bin/osascript",
                "-e",
                "on run argv\n"
                ' display alert "Ethernity" message (item 1 of argv) as critical\nend run',
                message,
            ],
            check=False,
        )
    else:
        print(message, file=sys.stderr)


def main() -> int:
    multiprocessing.freeze_support()
    try:
        # Finder and Start Menu do not provide a useful working directory for file dialogs.
        os.chdir(Path.home())
        with installer_lock():
            run_desktop()
    except (OSError, RuntimeError, webbrowser.Error) as error:
        message = str(error) or "The browser did not connect. Open Ethernity again to retry."
        show_error(message)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
