"""Distribution metadata must describe the actual bytes and preserve release policy."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from scripts import package_pyinstaller
from tooling.release import installers, inventory, python_package


def test_windows_archive_preserves_tiny_files_without_dangerous_expansion(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    files = {
        "ethernity.exe": b"executable" * 1000,
        "_internal/INSTALLER": b"uv",
        "_internal/flag": b"1",
        "_internal/py.typed": b"",
    }
    for name, content in files.items():
        path = tmp_path / "dist/ethernity" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    for name, value in {
        "RELEASE_TAG": "v1.2.0",
        "TARGET_OS": "windows",
        "TARGET_ARCH": "x64",
        "RUNNER_ARCH": "x64",
        "PACKAGER": "pyinstaller",
        "PACKAGE_MODE": "onedir",
    }.items():
        monkeypatch.setenv(name, value)
    package_pyinstaller.main()
    archive = tmp_path / "ethernity-v1.2.0-windows-x64.zip"
    with zipfile.ZipFile(archive) as zipped:
        assert len(zipped.infolist()) == len(files)
        for name, content in files.items():
            info = zipped.getinfo(f"ethernity-v1.2.0-windows-x64/{name}")
            assert zipped.read(info) == content
            assert info.compress_size <= info.file_size


@pytest.mark.parametrize("tag", ["v1.2.0", "v1.2.0rc1"])
def test_installer_assets_are_bound_to_the_same_release(tmp_path, tag):
    generated = {"install.sh", "install.ps1", "SHA256SUMS", "MinorGlitch.Ethernity.yaml"}
    for name in inventory.release_files(tag, signed=False):
        if name not in generated:
            (tmp_path / name).write_bytes(name.encode())
    installers.prepare(tmp_path, tag, "MinorGlitch/ethernity")
    inventory.validate_files(tmp_path, inventory.release_files(tag, signed=False))
    for line in (tmp_path / "SHA256SUMS").read_text().splitlines():
        checksum, name = line.split("  ")
        assert checksum == hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
    version = tag.removeprefix("v")
    assert f"version='{version}'" in (tmp_path / "install.sh").read_text()
    assert f"[string]$Version = '{version}'" in (tmp_path / "install.ps1").read_text()
    manifest = tmp_path / "MinorGlitch.Ethernity.yaml"
    if tag == "v1.2.0":
        text = manifest.read_text()
        archive = tmp_path / "ethernity-v1.2.0-windows-x64.zip"
        assert hashlib.sha256(archive.read_bytes()).hexdigest().upper() in text
        assert f"RelativeFilePath: {archive.stem}/ethernity.exe" in text
        assert f"releases/download/{tag}/{archive.name}" in text
    else:
        assert not manifest.exists()


def test_incomplete_release_cannot_generate_checksums(tmp_path):
    with pytest.raises(FileNotFoundError):
        installers.prepare(tmp_path, "v1.2.0", "MinorGlitch/ethernity")
    assert not (tmp_path / "SHA256SUMS").exists()


@pytest.fixture
def python_release(monkeypatch):
    class Release:
        state = {"draft": False, "prerelease": False}

        def __init__(self, repo):
            self.repo = repo

        def release(self, tag):
            return self.state

        def download(self, tag, name, directory):
            path = directory / name
            path.write_bytes(name.encode())
            return path

    monkeypatch.setattr(python_package, "GitHub", Release)
    return Release


def test_pypi_uses_verified_release_bytes_without_rebuilding(tmp_path, monkeypatch, python_release):
    commands = []
    monkeypatch.setattr(python_package, "run", lambda *args: commands.append(args))
    python_package.prepare("MinorGlitch/ethernity", "v1.2.0", tmp_path)
    assert (
        tmp_path / "ethernity_paper-1.2.0.tar.gz"
    ).read_bytes() == b"ethernity-source-v1.2.0.tar.gz"
    assert (tmp_path / "ethernity_paper-1.2.0-py3-none-any.whl").exists()
    assert len(commands) == 2
    assert all(command[:2] == ("cosign", "verify-blob") for command in commands)
    assert all("--certificate-identity-regexp" in command for command in commands)
    assert all("--certificate-oidc-issuer" in command for command in commands)


@pytest.mark.parametrize("state", [None, {"draft": True}, {"draft": False, "prerelease": True}])
def test_pypi_refuses_unpublished_or_prerelease(tmp_path, python_release, state):
    python_release.state = state
    with pytest.raises(ValueError, match="published stable"):
        python_package.prepare("MinorGlitch/ethernity", "v1.2.0", tmp_path)
    assert not list(tmp_path.iterdir())


def test_pypi_stops_on_bad_signature(tmp_path, monkeypatch, python_release):
    def bad_signature(*args):
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(python_package, "run", bad_signature)
    with pytest.raises(subprocess.CalledProcessError):
        python_package.prepare("MinorGlitch/ethernity", "v1.2.0", tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "version,branch_allowed",
    [
        ("1.2.0", False),
        ("1.2.0.post1", False),
        ("1.2.0a1", True),
        ("1.2.0b1", True),
        ("1.2.0rc1", True),
        ("1.2.0.dev1", True),
    ],
)
def test_installer_signature_identity_limits(version, branch_allowed):
    if os.name == "nt":
        source = Path("install.ps1").read_text()
        start = source.index("            $branchIdentity =")
        end = source.index("            & $cosign.Source", start)
        code = (
            "$Version = $env:TEST_VERSION; $tag = 'v' + $Version;\n"
            + source[start:end]
            + "\nWrite-Output $identity"
        )
        command = ["powershell", "-NoProfile", "-Command", code]
    else:
        source = Path("install.sh").read_text()
        start = source.index("    escaped_version=")
        end = source.index("    cosign verify-blob", start)
        code = (
            'version="$TEST_VERSION"; repo=https://github.com/MinorGlitch/ethernity\n'
            + source[start:end]
            + '\nprintf "%s" "$identity"'
        )
        command = [shutil.which("sh"), "-c", code]
    pattern = subprocess.check_output(
        command, text=True, env={**os.environ, "TEST_VERSION": version}
    ).strip()
    prefix = "https://github.com/MinorGlitch/ethernity/.github/workflows/pyinstaller.yml@refs/"
    assert re.fullmatch(pattern, prefix + f"tags/v{version}")
    assert re.fullmatch(pattern, prefix + "heads/master")
    assert bool(re.fullmatch(pattern, prefix + "heads/dev/preview")) is branch_allowed
    assert not re.fullmatch(pattern, prefix + "tags/v9.9.9")
    assert not re.fullmatch(pattern, prefix.replace("MinorGlitch", "attacker") + "heads/preview")
