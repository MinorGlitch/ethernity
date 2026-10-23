"""Exercise publication and rollback with real Windows directory locks."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
import zipfile
from contextlib import ExitStack, contextmanager
from pathlib import Path

import pytest
from tooling.release import install_smoke
from tooling.release.publish import digest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows installer and file locks")


def _wait_for(predicate, process: subprocess.Popen, description: str) -> None:
    deadline = time.monotonic() + 30
    while not predicate():
        assert process.poll() is None, f"Installer exited before {description}"
        assert time.monotonic() < deadline, f"Timed out waiting for {description}"
        time.sleep(0.02)


def _replacement_archive(directory: Path) -> Path:
    """A version probe lets the test lock its directory before publication."""
    source = directory / "replacement.cs"
    source.write_text(
        """
using System;
using System.IO;
using System.Threading;
class Program {
    static int Main() {
        string ready = Environment.GetEnvironmentVariable("ETHERNITY_INSTALL_TEST_READY");
        if (!String.IsNullOrEmpty(ready)) {
            File.WriteAllText(ready + ".tmp", AppDomain.CurrentDomain.BaseDirectory);
            File.Move(ready + ".tmp", ready);
            while (!File.Exists(ready + ".continue")) Thread.Sleep(20);
        }
        Console.WriteLine("ethernity 0.0.2");
        return 0;
    }
}
""",
        encoding="ascii",
    )
    executable = directory / "replacement.exe"
    compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    install_smoke.run(str(compiler), "/nologo", f"/out:{executable}", str(source))
    archive = directory / "ethernity-v0.0.2-windows-x64.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.write(executable, f"{archive.stem}/ethernity.exe")
    return archive


@contextmanager
def _directory_lock(directory: Path):
    # A handle without FILE_SHARE_DELETE blocks an atomic directory rename.
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    )
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel.CloseHandle.restype = ctypes.c_int
    handle = kernel.CreateFileW(str(directory), 0, 3, None, 3, 0x02000000, None)
    assert handle != ctypes.c_void_p(-1).value, ctypes.get_last_error()
    try:
        yield
    finally:
        assert kernel.CloseHandle(handle)


def _finish_probe(process: subprocess.Popen | None, proceed: Path) -> None:
    proceed.touch()
    if process is not None:
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


@pytest.mark.parametrize("release_lock", [True, False], ids=["transient-lock", "persistent-lock"])
def test_windows_installer_publishes_or_rolls_back_a_locked_replacement(
    tmp_path: Path, release_lock: bool
) -> None:
    root = tmp_path / "installation with spaces"
    command, executable, flags, remove = install_smoke.installer_command(root, tmp_path, "windows")
    checksums = tmp_path / "SHA256SUMS"

    def args(archive: Path, version: str) -> list[str]:
        checksums.write_text(f"{digest(archive)}  {archive.name}\n", encoding="ascii")
        return [*command, flags[0], version, flags[1], str(archive), flags[2], str(checksums)]

    old = install_smoke.fixture(tmp_path, "v0.0.1", "windows", "x64")
    original_path = install_smoke.windows_user_path()
    locks = ExitStack()
    process = None
    ready = tmp_path / "probe-ready"
    proceed = Path(f"{ready}.continue")
    log = tmp_path / "install.log"
    try:
        install_smoke.run(*args(old, "v0.0.1"))
        installed_path = install_smoke.windows_user_path()
        replacement = _replacement_archive(tmp_path)
        with log.open("w", encoding="utf-8") as output:
            process = subprocess.Popen(
                [*args(replacement, "v0.0.2"), "-Verbose"],
                stdout=output,
                stderr=subprocess.STDOUT,
                env={**os.environ, "ETHERNITY_INSTALL_TEST_READY": str(ready)},
            )
            _wait_for(ready.exists, process, "the replacement probe")
            candidate = Path(ready.read_text(encoding="utf-8-sig"))
            locks.enter_context(_directory_lock(candidate))
            proceed.touch()
            _wait_for(
                lambda: "Waiting for Windows to release" in log.read_text(encoding="utf-8"),
                process,
                "the blocked publication attempt",
            )
            assert not (root / "current").exists()
            assert len(list(root.glob(".stage-*/previous/ethernity.exe"))) == 1
            if release_lock:
                locks.close()
            result = process.wait(timeout=30)
        output_text = log.read_text(encoding="utf-8")
        assert (result == 0) == release_lock, output_text
        expected = "0.0.2" if release_lock else "0.0.1"
        assert install_smoke.run(str(executable), "--version") == f"ethernity {expected}"
        assert (root / "current/obsolete.txt").exists() is not release_lock
        assert install_smoke.windows_user_path() == installed_path
        assert not (root / ".install-lock").exists()
        if release_lock:
            assert not list(root.glob(".stage-*"))
        else:
            assert "Could not move" in output_text
            assert not list(root.glob(".stage-*/previous"))
    finally:
        locks.close()
        _finish_probe(process, proceed)
        if (root / ".ethernity-install").exists():
            install_smoke.run(*command, remove)
        assert install_smoke.windows_user_path().strip(";") == original_path.strip(";")
