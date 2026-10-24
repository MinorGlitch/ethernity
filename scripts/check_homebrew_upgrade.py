#!/usr/bin/env python3
"""Exercise Homebrew's upgrade path from a minimal old keg to the real release bottle."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import tarfile
import tempfile
from pathlib import Path

OLD_VERSION = "0.0.1"
OBSOLETE_COMMAND = "ethernity-upgrade-obsolete"


def run(*args: str, capture: bool = False) -> str:
    result = subprocess.run(
        args, check=True, text=True, stdout=subprocess.PIPE if capture else None, timeout=300
    )
    return (result.stdout or "").strip()


def old_formula(directory: Path) -> str:
    """Use a real Homebrew install, including a command absent from the new version."""
    archive = directory / f"ethernity-{OLD_VERSION}.tar.gz"
    script = f"#!/bin/sh\nprintf 'ethernity {OLD_VERSION}\\n'\n".encode("ascii")
    with tarfile.open(archive, "w:gz") as stream:
        for name in ("ethernity", OBSOLETE_COMMAND):
            member = tarfile.TarInfo(f"ethernity-{OLD_VERSION}/{name}")
            member.mode = 0o755
            member.size = len(script)
            stream.addfile(member, io.BytesIO(script))
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    return f'''class Ethernity < Formula
  desc "Homebrew upgrade test fixture"
  homepage "https://github.com/MinorGlitch/ethernity"
  url {json.dumps(archive.as_uri())}
  version "{OLD_VERSION}"
  sha256 "{checksum}"
  license "GPL-3.0-or-later"

  def install
    bin.install "ethernity", "{OBSOLETE_COMMAND}"
  end
end
'''


def installed() -> bool:
    # A named `brew list --versions` exits with status 1 when absent. Listing
    # installed formulae succeeds in both states and still exposes real failures.
    return any(
        line.split()[0] == "ethernity"
        for line in run("brew", "list", "--formula", "--versions", capture=True).splitlines()
    )


def check_upgraded_install(
    formula_ref: str, command: Path, obsolete: Path, expected_version: str
) -> None:
    if run(str(command), "--version", capture=True) != expected_version:
        raise AssertionError("upgrade did not activate the release version")
    if obsolete.exists() or obsolete.is_symlink():
        raise AssertionError("upgrade left the old command linked")
    keg = Path(run("brew", "--prefix", formula_ref, capture=True))
    receipt = json.loads((keg / "INSTALL_RECEIPT.json").read_text(encoding="utf-8"))
    if not receipt["poured_from_bottle"]:
        raise AssertionError("upgrade did not use the release bottle")


def verify_upgrade(formula_ref: str, bottle: Path, expected_version: str) -> None:
    bottle = bottle.resolve(strict=True)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/ethernity", formula_ref):
        raise ValueError("expected a fully qualified tap/ethernity formula")
    if installed():
        raise ValueError("upgrade check requires Ethernity to be uninstalled first")
    tap = formula_ref.rsplit("/", 1)[0]
    formula = Path(run("brew", "--repository", tap, capture=True)) / "Formula/ethernity.rb"
    original = formula.read_text(encoding="utf-8")
    prefix = Path(run("brew", "--prefix", capture=True))
    command = prefix / "bin/ethernity"
    obsolete = prefix / "bin" / OBSOLETE_COMMAND
    if any(path.exists() or path.is_symlink() for path in (command, obsolete)):
        raise ValueError("upgrade check would overwrite existing commands")

    with tempfile.TemporaryDirectory(prefix="ethernity-brew-upgrade-") as temporary:
        try:
            formula.write_text(old_formula(Path(temporary)), encoding="utf-8")
            run("brew", "install", "--build-from-source", formula_ref)
            if run(str(command), "--version", capture=True) != f"ethernity {OLD_VERSION}":
                raise AssertionError("old version was not installed")
            if not obsolete.is_symlink():
                raise AssertionError("old command was not linked")

            formula.write_text(original, encoding="utf-8")
            run("brew", "trust", "--formula", formula_ref)
            # Homebrew supports local bottles in developer mode. The caller scopes
            # that setting to this check, just as for bottle install and reinstall.
            run("brew", "upgrade", str(bottle.resolve()))
            check_upgraded_install(formula_ref, command, obsolete, expected_version)
            run("brew", "test", formula_ref)
            # Homebrew normally keeps older kegs when automatic cleanup is disabled.
            run("brew", "cleanup", formula_ref)
        finally:
            formula.write_text(original, encoding="utf-8")
            if installed():
                run("brew", "uninstall", "--force", formula_ref)
        if any(path.exists() or path.is_symlink() for path in (command, obsolete)):
            raise AssertionError("uninstall left an application command behind")
    print(
        f"Homebrew {OLD_VERSION} -> {expected_version}: upgrade, formula test and uninstall passed"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--formula", required=True)
    parser.add_argument("--bottle", type=Path, required=True)
    parser.add_argument("--expected-version", required=True)
    args = parser.parse_args()
    if os.environ.get("HOMEBREW_DEVELOPER") != "1":
        parser.error("local bottle checks require HOMEBREW_DEVELOPER=1")
    verify_upgrade(args.formula, args.bottle, args.expected_version)


if __name__ == "__main__":
    main()
