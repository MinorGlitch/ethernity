"""Exercise direct installers against the real platform archive in disposable paths."""

from __future__ import annotations

import io
import os
import platform
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path

from tooling.release import smoke
from tooling.release.publish import digest

ROOT = Path(__file__).resolve().parents[2]


def run(*args: str, success: bool = True) -> str:
    result = subprocess.run(
        args, encoding="utf-8", errors="replace", capture_output=True, check=False, timeout=180
    )
    if (result.returncode == 0) != success:
        raise AssertionError(f"Unexpected result for {args}:\n{result.stdout}\n{result.stderr}")
    return result.stdout.strip()


def fixture(directory: Path, tag: str, target: str, arch: str, *, broken: bool = False) -> Path:
    """A runnable previous version proves stale files are removed on upgrade."""
    stem = f"ethernity-{tag}-{target}-{arch}"
    tree = directory / stem
    tree.mkdir()
    (tree / "obsolete.txt").write_text("old version only", encoding="ascii")
    version = tag.removeprefix("v")
    if target == "windows":
        source = directory / f"{tag}.cs"
        source.write_text(
            'class Program { static int Main() { System.Console.WriteLine("ethernity '
            + version
            + '"); return '
            + ("1" if broken else "0")
            + "; } }",
            encoding="ascii",
        )
        compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
        run(str(compiler), "/nologo", f"/out:{tree / 'ethernity.exe'}", str(source))
        archive = directory / f"{stem}.zip"
        with zipfile.ZipFile(archive, "w") as stream:
            for path in tree.iterdir():
                stream.write(path, f"{stem}/{path.name}")
    else:
        executable = tree / "ethernity"
        executable.write_text(
            f"#!/bin/sh\nprintf 'ethernity {version}\\n'\nexit {int(broken)}\n", encoding="ascii"
        )
        executable.chmod(0o755)
        archive = directory / f"{stem}.tar.gz"
        with tarfile.open(archive, "w:gz") as stream:
            stream.add(tree, arcname=stem)
    return archive


def invalid_archive(directory: Path, tag: str, target: str, arch: str, member: str) -> Path:
    """Archives with a valid checksum must still pass layout and executable checks."""
    stem = f"ethernity-{tag}-{target}-{arch}"
    if target == "windows":
        archive = directory / f"{stem}.zip"
        with zipfile.ZipFile(archive, "w") as stream:
            stream.writestr(f"{stem}/{member}", b"invalid")
    else:
        archive = directory / f"{stem}.tar.gz"
        with tarfile.open(archive, "w:gz") as stream:
            entry = tarfile.TarInfo(f"{stem}/{member}")
            entry.size = 7
            stream.addfile(entry, io.BytesIO(b"invalid"))
    return archive


def installer_command(root: Path, bin_dir: Path, target: str):
    if target == "windows":
        command = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "install.ps1"),
            "-InstallRoot",
            str(root),
        ]
        executable = root / "current/ethernity.exe"
        flags = ("-Version", "-Archive", "-Checksums")
        remove = "-Uninstall"
    else:
        command = [
            "sh",
            str(ROOT / "install.sh"),
            "--install-root",
            str(root),
            "--bin-dir",
            str(bin_dir),
        ]
        executable = bin_dir / "ethernity"
        flags = ("--version", "--archive", "--checksums")
        remove = "--uninstall"

    return command, executable, flags, remove


def reject_foreign_uninstall(root: Path, command: list[str], remove: str) -> None:
    root.mkdir()
    (root / "my-files.txt").write_text("keep", encoding="ascii")
    run(*command, remove, success=False)
    assert (root / "my-files.txt").read_text(encoding="ascii") == "keep"
    (root / "my-files.txt").unlink()
    root.rmdir()


def exercise(archive: Path, tag: str, target: str, arch: str, directory: Path) -> None:
    root = directory / "installation with spaces"
    bin_dir = directory / "commands with spaces"
    sentinel = directory / "keep-my-backup.txt"
    sentinel.write_text("keep", encoding="ascii")
    checksums = directory / "SHA256SUMS"
    original_path = windows_user_path() if target == "windows" else ""
    command, executable, flags, remove = installer_command(root, bin_dir, target)

    def install(path: Path, version: str, *, success: bool = True, corrupt: bool = False) -> None:
        checksum = "0" * 64 if corrupt else digest(path)
        checksums.write_text(f"{checksum}  {path.name}\n", encoding="ascii")
        run(
            *command,
            flags[0],
            version,
            flags[1],
            str(path),
            flags[2],
            str(checksums),
            success=success,
        )

    try:
        old = fixture(directory, "v0.0.1", target, arch)
        install(old, "0.0.1")
        assert run(str(executable), "--version") == "ethernity 0.0.1"
        # Mandatory checksum failure must leave the old application intact.
        install(archive, tag, success=False, corrupt=True)
        assert run(str(executable), "--version") == "ethernity 0.0.1"
        broken = fixture(directory, "v0.0.2", target, arch, broken=True)
        install(broken, "0.0.2", success=False)
        assert run(str(executable), "--version") == "ethernity 0.0.1"
        for member in ("missing-executable.txt", "../../outside.txt"):
            invalid = invalid_archive(directory, "v0.0.3", target, arch, member)
            install(invalid, "0.0.3", success=False)
            assert not (directory / "outside.txt").exists()
            assert run(str(executable), "--version") == "ethernity 0.0.1"
        # Preserve the layout produced by the legacy Windows installer as well.
        if target == "windows":
            (root / ".ethernity-install").unlink()
            (root / "installed-version.txt").write_text("v0.0.1", encoding="ascii")
        # Upgrade to the real release, then reinstall it. Exercise the installed copy.
        install(archive, tag)
        assert not (root / "current/obsolete.txt").exists()
        assert run(str(executable), "--version") == f"ethernity {tag.removeprefix('v')}"
        smoke.smoke(str(executable))
        install(archive, tag)
        assert run(str(executable), "--version") == f"ethernity {tag.removeprefix('v')}"
        if target == "windows":
            entries = windows_user_path().split(";")
            installed_entries = [
                entry
                for entry in entries
                if entry and Path(entry).exists() and Path(entry).samefile(root / "current")
            ]
            assert len(installed_entries) == 1, f"Expected one installed command path: {entries}"
        run(*command, remove)
        assert not executable.exists()
        assert not root.exists()
        if target == "windows":
            assert windows_user_path().strip(";") == original_path.strip(";")
        run(*command, remove)  # Repeated uninstall is harmless.
        assert sentinel.read_text(encoding="ascii") == "keep"
        # An arbitrary directory must never become an uninstall target.
        reject_foreign_uninstall(root, command, remove)
        print(f"{target}/{arch}: install, failed upgrade, upgrade, reinstall and uninstall passed")
    finally:
        if (root / ".ethernity-install").exists() or (root / "installed-version.txt").exists():
            run(*command, remove)


def windows_user_path() -> str:
    return run(
        "powershell",
        "-NoProfile",
        "-Command",
        "[Environment]::GetEnvironmentVariable('Path', 'User')",
    )


def main() -> None:
    tag = os.environ["RELEASE_TAG"]
    target = os.environ.get("TARGET_OS", platform.system().lower())
    arch = os.environ["TARGET_ARCH"]
    suffix = "zip" if target == "windows" else "tar.gz"
    archive = Path(f"ethernity-{tag}-{target}-{arch}.{suffix}").resolve()
    with tempfile.TemporaryDirectory(prefix="ethernity-install-check-") as temp:
        exercise(archive, tag, target, arch, Path(temp))


if __name__ == "__main__":
    main()
