#!/usr/bin/env python3
from __future__ import annotations

import os
import platform
import ssl
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
import shutil
from pathlib import Path

import certifi

_AGE_VERSION = "1.3.1"
_AGE_REPO = "FiloSottile/age"
_AGE_ARTIFACTS = {
    ("darwin", "arm64"),
    ("freebsd", "amd64"),
    ("linux", "amd64"),
    ("linux", "arm"),
    ("linux", "arm64"),
    ("windows", "amd64"),
}


def download_age_binary(*, dest_path: Path, binary_name: str, path_env: str) -> None:
    archive_name, url, archive_kind = _age_download_spec(path_env=path_env)
    with tempfile.TemporaryDirectory() as tmpdir:
        archive_path = Path(tmpdir) / archive_name
        _download_file(url, archive_path)
        tmp_binary = Path(tmpdir) / binary_name
        if archive_kind == "zip":
            _extract_from_zip(archive_path, tmp_binary, binary_name)
        else:
            _extract_from_tar(archive_path, tmp_binary, binary_name)
        tmp_binary.replace(dest_path)
    if os.name != "nt":
        os.chmod(dest_path, 0o755)


def _age_download_spec(*, path_env: str) -> tuple[str, str, str]:
    try:
        os_name = _age_platform_name()
        arch = _age_arch_name()
    except RuntimeError as exc:
        supported = ", ".join(sorted(f"{name}-{cpu}" for name, cpu in _AGE_ARTIFACTS))
        raise RuntimeError(
            f"{exc}. Supported: {supported}. Set {path_env} to a local age binary."
        ) from exc
    if (os_name, arch) not in _AGE_ARTIFACTS:
        supported = ", ".join(sorted(f"{name}-{cpu}" for name, cpu in _AGE_ARTIFACTS))
        raise RuntimeError(
            f"age release does not include {os_name}-{arch}. Supported: {supported}. "
            f"Set {path_env} to a local age binary."
        )
    if os_name == "windows":
        archive_kind = "zip"
        archive_name = f"age-v{_AGE_VERSION}-{os_name}-{arch}.zip"
    else:
        archive_kind = "tar.gz"
        archive_name = f"age-v{_AGE_VERSION}-{os_name}-{arch}.tar.gz"
    url = f"https://github.com/{_AGE_REPO}/releases/download/v{_AGE_VERSION}/{archive_name}"
    return archive_name, url, archive_kind


def _age_platform_name() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform.startswith("freebsd"):
        return "freebsd"
    raise RuntimeError(f"unsupported platform for age download: {sys.platform}")


def _age_arch_name() -> str:
    if sys.platform == "win32":
        return "amd64"
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "amd64"
    if machine in ("arm64", "aarch64"):
        return "arm64"
    if machine in ("arm", "armv6", "armv6l", "armv7", "armv7l", "armv8l", "armhf"):
        return "arm"
    raise RuntimeError(f"unsupported architecture for age download: {machine}")


def _download_file(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "ethernity"})
    context = ssl.create_default_context(cafile=certifi.where())
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(request, timeout=60, context=context) as resp:
                with open(dest, "wb") as handle:
                    shutil.copyfileobj(resp, handle)
            return
        except Exception as exc:
            if attempt < 3:
                time.sleep(1.5 * attempt)
                continue
            detail = str(exc)
            if isinstance(exc, urllib.error.HTTPError):
                detail = f"HTTP {exc.code} {exc.reason}"
            elif isinstance(exc, urllib.error.URLError):
                detail = str(exc.reason)
            raise RuntimeError(f"failed to download age from {url}: {detail}") from exc


def _extract_from_zip(archive_path: Path, dest: Path, binary_name: str) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        member = next(
            (
                name
                for name in archive.namelist()
                if name.endswith(f"/{binary_name}") or name == binary_name
            ),
            None,
        )
        if member is None:
            raise RuntimeError("age binary not found in zip archive")
        with archive.open(member) as src, open(dest, "wb") as handle:
            shutil.copyfileobj(src, handle)


def _extract_from_tar(archive_path: Path, dest: Path, binary_name: str) -> None:
    with tarfile.open(archive_path, "r:gz") as archive:
        member = next(
            (
                entry
                for entry in archive.getmembers()
                if entry.isfile()
                and (entry.name.endswith(f"/{binary_name}") or entry.name == binary_name)
            ),
            None,
        )
        if member is None:
            raise RuntimeError("age binary not found in tar archive")
        extracted = archive.extractfile(member)
        if extracted is None:
            raise RuntimeError("failed to extract age binary from tar archive")
        with extracted, open(dest, "wb") as handle:
            shutil.copyfileobj(extracted, handle)
