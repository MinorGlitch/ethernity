"""Build desktop installers from the same verified PyInstaller outputs as the CLI archives."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from tooling.release.inventory import validate_tag

ROOT = Path(__file__).resolve().parents[2]
PRODUCT_ID = "MinorGlitch.Ethernity.Desktop"


def windows_installer(source: Path, output: Path, tag: str, compiler: Path) -> Path:
    version = tag.removeprefix("v")
    parsed = validate_tag(tag, version)
    binary_version = ".".join(map(str, parsed.release[:4]))
    for name in ("ethernity.exe", "ethernity-desktop.exe"):
        if not (source / name).is_file():
            raise ValueError(f"Missing PyInstaller executable: {source / name}")
    output.mkdir(parents=True, exist_ok=True)
    name = f"ethernity-{tag}-windows-x64-setup"
    with tempfile.TemporaryDirectory(prefix="ethernity-setup-") as temporary:
        payload = Path(temporary) / "payload"
        shutil.copytree(source, payload)
        (payload / ".ethernity-desktop").write_text(PRODUCT_ID, encoding="ascii")
        subprocess.run(
            [
                str(compiler),
                f"/DAppVersion={version}",
                f"/DBinaryVersion={binary_version}",
                f"/DSourceDir={payload}",
                f"/DOutputDir={output.resolve()}",
                f"/DOutputName={name}",
                str(ROOT / "packaging/windows/ethernity.iss"),
            ],
            check=True,
        )
    return output / f"{name}.exe"


def macos_dmg(source: Path, output: Path, tag: str) -> Path:
    validate_tag(tag, tag.removeprefix("v"))
    if not (source / "Contents/MacOS/ethernity-desktop").is_file():
        raise ValueError(f"Missing PyInstaller app: {source}")
    output.mkdir(parents=True, exist_ok=True)
    result = output / f"ethernity-{tag}-macos-arm64.dmg"
    with tempfile.TemporaryDirectory(prefix="ethernity-dmg-") as temporary:
        stage = Path(temporary) / "volume"
        stage.mkdir()
        subprocess.run(["ditto", str(source), str(stage / "Ethernity.app")], check=True)
        (stage / "Applications").symlink_to("/Applications", target_is_directory=True)
        subprocess.run(
            [
                "hdiutil",
                "create",
                "-ov",
                "-volname",
                "Ethernity",
                "-srcfolder",
                str(stage),
                "-format",
                "UDZO",
                str(result.resolve()),
            ],
            check=True,
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--output", type=Path, default=Path.cwd())
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--compiler", type=Path)
    args = parser.parse_args()
    if sys.platform == "win32":
        if args.compiler is None:
            parser.error("--compiler must point to the Inno Setup compiler")
        result = windows_installer(args.dist / "ethernity", args.output, args.tag, args.compiler)
    elif sys.platform == "darwin":
        result = macos_dmg(args.dist / "Ethernity.app", args.output, args.tag)
    else:
        parser.error("desktop packages are built on Windows and macOS")
    print(f"Created {result}")


if __name__ == "__main__":
    main()
