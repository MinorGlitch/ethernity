"""Install, upgrade, reinstall and remove the native desktop distributions."""

from __future__ import annotations

import argparse
import asyncio
import json
import plistlib
import shutil
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from tooling.release import desktop_packages, smoke
from tooling.release.desktop_smoke import check_desktop, smoke_desktop
from tooling.release.install_smoke import run

PREVIOUS = "0.0.1"
REGISTRY = (
    "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\"
    + desktop_packages.PRODUCT_ID
    + "_is1"
)


def windows_state() -> dict:
    return json.loads(
        run(
            "powershell",
            "-NoProfile",
            "-Command",
            "$ErrorActionPreference = 'Stop'; "
            f"$key = Get-ItemProperty -LiteralPath '{REGISTRY}' -ErrorAction SilentlyContinue; "
            "$programs = [Environment]::GetFolderPath('Programs'); "
            "$desktop = [Environment]::GetFolderPath('DesktopDirectory'); "
            "$shell = New-Object -ComObject WScript.Shell; "
            "$targets = @($programs, $desktop) | ForEach-Object { "
            "$link = Join-Path $_ 'Ethernity.lnk'; "
            "if (Test-Path -LiteralPath $link) { $shell.CreateShortcut($link).TargetPath } }; "
            "@{ version = $key.DisplayVersion; location = $key.InstallLocation; "
            "path = [Environment]::GetEnvironmentVariable('Path', 'User'); "
            "programs = $programs; desktop = $desktop; targets = @($targets) } | ConvertTo-Json",
        )
    )


def check_windows_installation(root: Path, version: str) -> None:
    state = windows_state()
    assert state["version"] == version
    assert Path(state["location"]).samefile(root)
    assert len(state["targets"]) == 2
    executable = root / f"app-{version}" / "ethernity-desktop.exe"
    assert all(Path(target).samefile(executable) for target in state["targets"])


def windows(source: Path, installer: Path, compiler: Path, version: str, directory: Path) -> None:
    before = windows_state()
    shortcuts = [Path(before[name]) / "Ethernity.lnk" for name in ("programs", "desktop")]
    if before["version"] or any(path.exists() for path in shortcuts):
        raise RuntimeError(
            "Use a clean Windows account: an Ethernity desktop install already exists"
        )
    old_source = directory / "previous-payload"
    shutil.copytree(source, old_source)
    (old_source / "obsolete.txt").write_text("previous installer only", encoding="ascii")
    previous = desktop_packages.windows_installer(old_source, directory, f"v{PREVIOUS}", compiler)
    root = directory / "Programs with spaces" / "Ethernity"

    def install(package: Path, *, success: bool = True) -> None:
        run(
            str(package),
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/SP-",
            f"/DIR={root}",
            "/TASKS=desktopicon",
            success=success,
        )

    try:
        install(previous)
        check_windows_installation(root, PREVIOUS)
        old_runtime = root / f"app-{PREVIOUS}"
        smoke_desktop(old_runtime / "ethernity-desktop.exe")

        def reject_in_use_upgrade() -> None:
            install(installer, success=False)
            run(
                str(root / "unins000.exe"),
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                success=False,
            )
            assert windows_state()["version"] == PREVIOUS
            assert (old_runtime / "obsolete.txt").exists()

        asyncio.run(
            check_desktop(
                [str(old_runtime / "ethernity-desktop.exe")], while_running=reject_in_use_upgrade
            )
        )
        # Unknown directories are not obsolete Ethernity runtimes.
        foreign = root / "app-personal" / "my-notes.txt"
        foreign.parent.mkdir()
        foreign.write_text("keep", encoding="ascii")
        install(installer)
        assert not old_runtime.exists()
        runtime = root / f"app-{version}"
        assert not (runtime / "obsolete.txt").exists()
        smoke.smoke(str(runtime / "ethernity.exe"))
        install(installer)
        check_windows_installation(root, version)
        smoke_desktop(runtime / "ethernity-desktop.exe")
        run(str(root / "unins000.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")
        assert not runtime.exists()
        assert not (root / "unins000.exe").exists()
        assert not windows_state()["version"]
        assert not any(path.exists() for path in shortcuts)
        assert windows_state()["path"] == before["path"]
        assert foreign.read_text(encoding="ascii") == "keep"
        # The desktop installer must not take over a shell install's directory.
        marker = root / ".ethernity-install"
        marker.write_text("keep", encoding="ascii")
        install(installer, success=False)
        assert marker.read_text(encoding="ascii") == "keep"
        assert not windows_state()["version"]
    finally:
        if (root / "unins000.exe").exists():
            run(str(root / "unins000.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")


@contextmanager
def mounted(image: Path, directory: Path) -> Iterator[Path]:
    mount = directory / "mounted volume"
    run("hdiutil", "attach", str(image), "-readonly", "-nobrowse", "-mountpoint", str(mount))
    try:
        assert (mount / "Applications").is_symlink()
        assert (mount / "Applications").readlink() == Path("/Applications")
        yield mount / "Ethernity.app"
    finally:
        run("hdiutil", "detach", str(mount))


def app_version(app: Path) -> str:
    return plistlib.loads((app / "Contents/Info.plist").read_bytes())["CFBundleShortVersionString"]


def macos(source: Path, image: Path, version: str, directory: Path) -> None:
    old_app = directory / "previous" / "Ethernity.app"
    run("ditto", str(source), str(old_app))
    info_path = old_app / "Contents/Info.plist"
    info = plistlib.loads(info_path.read_bytes())
    info.update(CFBundleVersion=PREVIOUS, CFBundleShortVersionString=PREVIOUS)
    info_path.write_bytes(plistlib.dumps(info))
    (old_app / "Contents/Resources/obsolete.txt").write_text("previous installer only")
    # The fixture changes signed metadata; refresh the same ad-hoc signature used by PyInstaller.
    run("codesign", "--force", "--deep", "--sign", "-", str(old_app))
    previous = desktop_packages.macos_dmg(old_app, directory, f"v{PREVIOUS}")
    app = directory / "Applications with spaces" / "Ethernity.app"
    with mounted(previous, directory) as mounted_app:
        run("ditto", str(mounted_app), str(app))
    assert app_version(app) == PREVIOUS
    smoke_desktop(app)

    with mounted(image, directory) as mounted_app:
        # Finder's Replace replaces the whole app, rather than merging old files into it.
        for _ in range(2):
            shutil.rmtree(app)
            run("ditto", str(mounted_app), str(app))
            assert app_version(app) == version
            assert not (app / "Contents/Resources/obsolete.txt").exists()
            run("codesign", "--verify", "--deep", "--strict", str(app))
    smoke.smoke(str(app / "Contents/MacOS/ethernity"))
    smoke_desktop(app)
    shutil.rmtree(app)
    assert not app.exists()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--packages", type=Path, default=Path.cwd())
    parser.add_argument("--compiler", type=Path)
    args = parser.parse_args()
    version = args.tag.removeprefix("v")
    with tempfile.TemporaryDirectory(prefix="ethernity-desktop-install-") as temporary:
        directory = Path(temporary)
        sentinel = directory / "keep-my-backup.txt"
        sentinel.write_text("keep", encoding="ascii")
        if sys.platform == "win32":
            if args.compiler is None:
                parser.error("--compiler must point to the Inno Setup compiler")
            windows(
                args.dist / "ethernity",
                args.packages / f"ethernity-{args.tag}-windows-x64-setup.exe",
                args.compiler,
                version,
                directory,
            )
        elif sys.platform == "darwin":
            macos(
                args.dist / "Ethernity.app",
                args.packages / f"ethernity-{args.tag}-macos-arm64.dmg",
                version,
                directory,
            )
        else:
            parser.error("desktop installation checks run on Windows and macOS")
        assert sentinel.read_text(encoding="ascii") == "keep"
    print("Desktop install, upgrade, reinstall, browser launch, recovery and uninstall passed")


if __name__ == "__main__":
    main()
