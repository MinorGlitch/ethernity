"""The native build matrix and release filenames share one source of truth."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path

from packaging.version import Version


@dataclass(frozen=True)
class Target:
    runner: str
    target_os: str
    target_arch: str
    archive_ext: str = "tar.gz"

    def stem(self, tag: str) -> str:
        return f"ethernity-{tag}-{self.target_os}-{self.target_arch}"


# Linux binaries are built and exercised on our oldest supported distribution.
TARGETS = (
    Target("ubuntu-22.04", "linux", "x64"),
    Target("ubuntu-22.04-arm", "linux", "arm64"),
    Target("macos-14", "macos", "arm64"),
    Target("windows-2022", "windows", "x64", "zip"),
)


def matrix() -> dict[str, list[dict[str, str]]]:
    return {"include": [asdict(target) for target in TARGETS]}


def validate_tag(tag: str, version: str) -> Version:
    if not re.fullmatch(r"v[0-9][0-9A-Za-z._-]*", tag) or tag != f"v{version}":
        raise ValueError(f"release tag {tag!r} does not match project version {version!r}")
    return Version(version)


def release_files(tag: str, *, signed: bool = True) -> tuple[str, ...]:
    archives = [(target.stem(tag), target.archive_ext) for target in TARGETS]
    archives.append((f"ethernity-source-{tag}", "tar.gz"))
    files = tuple(
        name for stem, ext in archives for name in (f"{stem}.{ext}", f"{stem}.sbom.cdx.json")
    )
    files += (
        f"ethernity-{tag}-windows-x64-setup.exe",
        f"ethernity-{tag}-macos-arm64.dmg",
        f"ethernity_paper-{tag.removeprefix('v')}-py3-none-any.whl",
        "install.sh",
        "install.ps1",
        "SHA256SUMS",
    )
    if re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        files += ("MinorGlitch.Ethernity.yaml",)
    return files + tuple(f"{name}.sigstore.json" for name in files) if signed else files


def validate_files(directory: Path, names: tuple[str, ...]) -> list[Path]:
    actual = {path.name for path in directory.iterdir()}
    if actual != set(names):
        raise ValueError(
            f"release file set mismatch: missing={set(names) - actual}, extra={actual - set(names)}"
        )
    files = [directory / name for name in names]
    if any(not path.is_file() or not path.stat().st_size for path in files):
        raise ValueError("release files must not be empty")
    return files
