"""Prepare installer metadata from the exact archives being published."""

from __future__ import annotations

import argparse
from pathlib import Path

from tooling.release.inventory import release_files, validate_files, validate_tag
from tooling.release.publish import digest


def winget_manifest(archive: Path, tag: str, url: str) -> str:
    version = validate_tag(tag, tag.removeprefix("v"))
    if version.is_prerelease or version.is_devrelease:
        raise ValueError("WinGet requires a stable release")
    return f"""# yaml-language-server: $schema=https://aka.ms/winget-manifest.singleton.1.9.0.schema.json
PackageIdentifier: MinorGlitch.Ethernity
PackageVersion: {version}
PackageLocale: en-US
Publisher: MinorGlitch
PackageName: Ethernity
PackageUrl: https://github.com/MinorGlitch/ethernity
License: GPL-3.0-or-later
LicenseUrl: https://github.com/MinorGlitch/ethernity/blob/{tag}/LICENSE
ShortDescription: Create encrypted paper backups and recover files offline.
InstallerType: zip
NestedInstallerType: portable
NestedInstallerFiles:
  - RelativeFilePath: ethernity-{tag}-windows-x64/ethernity.exe
    PortableCommandAlias: ethernity
Installers:
  - Architecture: x64
    InstallerUrl: {url}
    InstallerSha256: {digest(archive).upper()}
ManifestType: singleton
ManifestVersion: 1.9.0
"""


def prepare(directory: Path, tag: str, repo: str) -> None:
    """Add version-bound scripts, WinGet metadata, and mandatory archive checksums."""
    for name in ("install.sh", "install.ps1"):
        source = Path(name).read_text(encoding="utf-8")
        default = "version=''" if name.endswith(".sh") else "[string]$Version = ''"
        if source.count(default) != 1:
            raise ValueError(f"missing installer version default: {name}")
        source = source.replace(default, default[:-1] + tag.removeprefix("v") + "'", 1)
        (directory / name).write_text(source, encoding="utf-8")
    if "MinorGlitch.Ethernity.yaml" in release_files(tag, signed=False):
        archive = directory / f"ethernity-{tag}-windows-x64.zip"
        manifest = winget_manifest(
            archive, tag, f"https://github.com/{repo}/releases/download/{tag}/{archive.name}"
        )
        (directory / "MinorGlitch.Ethernity.yaml").write_text(manifest, encoding="utf-8")
    names = tuple(name for name in release_files(tag, signed=False) if name != "SHA256SUMS")
    files = validate_files(directory, names)
    (directory / "SHA256SUMS").write_text(
        "".join(f"{digest(path)}  {path.name}\n" for path in sorted(files)), encoding="ascii"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("release-files"))
    parser.add_argument("--tag", required=True)
    parser.add_argument("--repo", default="MinorGlitch/ethernity")
    args = parser.parse_args()
    prepare(args.directory, args.tag, args.repo)


if __name__ == "__main__":
    main()
