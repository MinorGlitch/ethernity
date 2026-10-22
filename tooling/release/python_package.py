"""Recover verified PyPI files from a published release, without rebuilding."""

from __future__ import annotations

import argparse
import re
import shutil
import tempfile
from pathlib import Path

from tooling.release.cli import OIDC_ISSUER
from tooling.release.github import GitHub, run
from tooling.release.inventory import validate_tag


def prepare(repo: str, tag: str, destination: Path) -> None:
    version = validate_tag(tag, tag.removeprefix("v"))
    github = GitHub(repo)
    release = github.release(tag)
    if release is None or release["draft"] or release["prerelease"]:
        raise ValueError("PyPI publication requires a published stable GitHub release")
    identity = (
        r"^https://github\.com/"
        + re.escape(repo)
        + r"/\.github/workflows/pyinstaller\.yml@refs/(tags/"
        + re.escape(tag)
        + "|heads/master)$"
    )
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise ValueError("Python distribution directory must be empty")
    names = (
        (f"ethernity-source-{tag}.tar.gz", f"ethernity_paper-{version}.tar.gz"),
        (
            f"ethernity_paper-{version}-py3-none-any.whl",
            f"ethernity_paper-{version}-py3-none-any.whl",
        ),
    )
    with tempfile.TemporaryDirectory() as temp:
        directory = Path(temp)
        for source, target in names:
            archive = github.download(tag, source, directory)
            bundle = github.download(tag, f"{source}.sigstore.json", directory)
            run(
                "cosign",
                "verify-blob",
                "--bundle",
                str(bundle),
                "--certificate-identity-regexp",
                identity,
                "--certificate-oidc-issuer",
                OIDC_ISSUER,
                str(archive),
            )
            shutil.copyfile(archive, destination / target)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--directory", type=Path, default=Path("python-dist"))
    args = parser.parse_args()
    prepare(args.repo, args.tag, args.directory)


if __name__ == "__main__":
    main()
