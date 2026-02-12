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

import os
import tarfile
import zipfile
from pathlib import Path
from typing import Final

PACKAGER_EXPECTED: Final = "pyinstaller"
PACKAGE_MODE_EXPECTED: Final = "onedir"
DIST_DIR: Final = Path("dist")
PYINSTALLER_DIR: Final = DIST_DIR / "ethernity"


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"missing required environment variable: {name}")
    return value


def _normalize_tag(tag: str) -> str:
    if tag.startswith("refs/tags/"):
        return tag.removeprefix("refs/tags/")
    return tag


def _normalize_os(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"ubuntu", "ubuntu-latest", "linux"}:
        return "linux"
    if normalized in {"macos", "macos-latest", "darwin"}:
        return "macos"
    if normalized in {"windows", "windows-latest", "win32"}:
        return "windows"
    raise SystemExit(f"unsupported ARTIFACT_OS value: {value}")


def _normalize_arch(value: str) -> str:
    normalized = value.strip().lower()
    aliases = {
        "x64": "x64",
        "amd64": "x64",
        "x86_64": "x64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }
    arch = aliases.get(normalized)
    if arch is None:
        raise SystemExit(f"unsupported ARTIFACT_ARCH value: {value}")
    return arch


def _iter_dist_files(base_dir: Path) -> list[Path]:
    files = [path for path in base_dir.rglob("*") if path.is_file()]
    return sorted(files, key=lambda path: path.as_posix())


def _ensure_dist_layout() -> None:
    if not DIST_DIR.exists():
        raise SystemExit("dist/ not found; run PyInstaller first")
    if not PYINSTALLER_DIR.is_dir():
        raise SystemExit("expected onedir output at dist/ethernity/")
    executable_candidates = [PYINSTALLER_DIR / "ethernity", PYINSTALLER_DIR / "ethernity.exe"]
    if not any(path.exists() for path in executable_candidates):
        raise SystemExit("expected ethernity executable in dist/ethernity/")
    if not _iter_dist_files(PYINSTALLER_DIR):
        raise SystemExit("dist/ethernity is empty")


def _archive_root_name(release_tag: str, artifact_os: str, artifact_arch: str) -> str:
    return f"ethernity-{release_tag}-{artifact_os}-{artifact_arch}"


def _create_zip(output: Path, archive_root: str) -> None:
    files = _iter_dist_files(PYINSTALLER_DIR)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zip_handle:
        for path in files:
            archive_name = (Path(archive_root) / path.relative_to(PYINSTALLER_DIR)).as_posix()
            info = zipfile.ZipInfo(filename=archive_name, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            zip_handle.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)


def _tar_filter(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    info.mtime = 0
    return info


def _create_tar_gz(output: Path, archive_root: str) -> None:
    with tarfile.open(output, "w:gz") as tar_handle:
        tar_handle.add(PYINSTALLER_DIR, arcname=archive_root, filter=_tar_filter)


def main() -> None:
    release_tag = _normalize_tag(_required_env("RELEASE_TAG"))
    artifact_os = _normalize_os(_required_env("ARTIFACT_OS"))
    artifact_arch = _normalize_arch(_required_env("ARTIFACT_ARCH"))
    runner_arch_raw = os.environ.get("RUNNER_ARCH", "").strip()
    packager = _required_env("PACKAGER").lower()
    package_mode = _required_env("PACKAGE_MODE").lower()
    if packager != PACKAGER_EXPECTED:
        raise SystemExit(f"PACKAGER must be {PACKAGER_EXPECTED!r}, got: {packager!r}")
    if package_mode != PACKAGE_MODE_EXPECTED:
        raise SystemExit(f"PACKAGE_MODE must be {PACKAGE_MODE_EXPECTED!r}, got: {package_mode!r}")
    if runner_arch_raw:
        runner_arch = _normalize_arch(runner_arch_raw)
        if runner_arch != artifact_arch:
            raise SystemExit(
                "ARTIFACT_ARCH does not match runner architecture: "
                f"{artifact_arch!r} vs {runner_arch!r}"
            )

    _ensure_dist_layout()
    archive_root = _archive_root_name(release_tag, artifact_os, artifact_arch)
    base_name = f"ethernity-{release_tag}-{artifact_os}-{artifact_arch}"
    if artifact_os == "windows":
        output = Path(f"{base_name}.zip")
        _create_zip(output, archive_root)
    else:
        output = Path(f"{base_name}.tar.gz")
        _create_tar_gz(output, archive_root)

    print(f"Created {output}")


if __name__ == "__main__":
    main()
