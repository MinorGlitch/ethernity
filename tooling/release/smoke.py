"""Exercise the installed package and check Linux's native library baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

from tooling.release.browser_smoke import smoke_browser

FIXTURE = Path("tests/fixtures/v1_2/extension_golden/base64/gzip_replacement_chain")


def check_glibc(directory: Path) -> None:
    for path in directory.rglob("*"):
        if not path.is_file():
            continue
        with path.open("rb") as stream:
            elf = stream.read(4) == b"\x7fELF"
        if not elf:
            continue
        versions = subprocess.check_output(["readelf", "--version-info", str(path)], text=True)
        required = {
            tuple(map(int, match.split("."))) for match in re.findall(r"GLIBC_([0-9.]+)", versions)
        }
        if any(version > (2, 35) for version in required):
            raise ValueError(f"{path} requires glibc newer than 2.35: {sorted(required)}")


def smoke(binary: str) -> None:
    subprocess.run([binary, "--help"], check=True)
    subprocess.run([binary, "--version"], check=True)
    smoke_browser(binary)
    scans = [
        FIXTURE / "chain/qr_document.pdf",
        *sorted((FIXTURE / "chain/extensions/01").glob("qr_document-01-*.pdf")),
    ]
    if len(scans) < 2:
        raise ValueError("missing root or extension smoke fixture")
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "recovered"
        args = [binary, "run", "restore"]
        for scan in scans:
            args.extend(["--scan", str(scan)])
        args.extend(
            ["--passphrase", "stable-v1_2-extension-passphrase", "--output", str(output), "--yes"]
        )
        subprocess.run(args, check=True)
        expected = json.loads((FIXTURE / "snapshot.json").read_text(encoding="utf-8"))["states"][
            "extension_01"
        ]
        actual = {
            path.relative_to(output).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in output.rglob("*")
            if path.is_file()
        }
        if actual != expected:
            raise ValueError("packaged executable did not recover the exact frozen file contents")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary")
    parser.add_argument("--glibc-directory", type=Path)
    args = parser.parse_args()
    if args.glibc_directory:
        check_glibc(args.glibc_directory)
    smoke(args.binary)


if __name__ == "__main__":
    main()
