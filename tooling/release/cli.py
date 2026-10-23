"""Commands used by the release workflow, with policy outside YAML."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from pathlib import Path

from tooling.release.github import GitHub, run
from tooling.release.inventory import matrix, release_files, validate_files, validate_tag
from tooling.release.precheck import check_release_commit
from tooling.release.publish import publish

OIDC_ISSUER = "https://token.actions.githubusercontent.com"


def sign(directory: Path, tag: str) -> None:
    files = validate_files(directory, release_files(tag, signed=False))
    identity = f"https://github.com/{os.environ['GITHUB_WORKFLOW_REF']}"
    for path in files:
        bundle = f"{path}.sigstore.json"
        run("cosign", "sign-blob", "--yes", "--bundle", bundle, str(path))
        run(
            "cosign",
            "verify-blob",
            "--bundle",
            bundle,
            "--certificate-identity",
            identity,
            "--certificate-oidc-issuer",
            OIDC_ISSUER,
            str(path),
        )


def verify_published(tag: str) -> None:
    github = GitHub(os.environ["GITHUB_REPOSITORY"])
    sha = os.environ["RELEASE_COMMIT_SHA"]
    check_release_commit(tag, sha)
    branch = ".+" if validate_tag(tag, tag.removeprefix("v")).is_prerelease else "master"
    identity = (
        "^https://github.com/"
        + re.escape(github.repo)
        + r"/\.github/workflows/pyinstaller\.yml@refs/(tags/"
        + re.escape(tag)
        + f"|heads/{branch})$"
    )
    with tempfile.TemporaryDirectory() as temp:
        directory = Path(temp)
        for name in release_files(tag):
            github.download(tag, name, directory)
        validate_files(directory, release_files(tag))
        for name in release_files(tag, signed=False):
            path = directory / name
            run(
                "cosign",
                "verify-blob",
                "--bundle",
                f"{path}.sigstore.json",
                "--certificate-identity-regexp",
                identity,
                "--certificate-oidc-issuer",
                OIDC_ISSUER,
                str(path),
            )
    check_release_commit(tag, sha)


def publish_release(directory: Path, tag: str) -> None:
    files = validate_files(directory, release_files(tag))
    sha = os.environ["RELEASE_COMMIT_SHA"]
    publish(
        GitHub(os.environ["GITHUB_REPOSITORY"]),
        tag,
        files,
        sha=sha,
        prerelease=os.environ["RELEASE_PRERELEASE"] == "true",
        draft=os.environ["RELEASE_DRAFT"] == "true",
        recheck=lambda: check_release_commit(tag, sha),
        ci_exception=os.environ.get("RELEASE_CI_EXCEPTION", ""),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("matrix", "sign", "publish", "verify-published"))
    parser.add_argument("--tag", default=os.environ.get("RELEASE_TAG", ""))
    parser.add_argument("--directory", type=Path, default=Path("release-files"))
    args = parser.parse_args()
    if args.command == "matrix":
        print(json.dumps(matrix()))
    elif args.command == "sign":
        sign(args.directory, args.tag)
    elif args.command == "verify-published":
        verify_published(args.tag)
    else:
        publish_release(args.directory, args.tag)


if __name__ == "__main__":
    main()
