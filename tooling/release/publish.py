"""Idempotent publication: compare existing bytes and only complete drafts."""

from __future__ import annotations

import hashlib
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tooling.release.github import GitHub


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def asset_names(release: dict[str, Any]) -> set[str]:
    names = [asset["name"] for asset in release["assets"]]
    if len(names) != len(set(names)):
        raise ValueError("duplicate remote release assets")
    return set(names)


def missing_files(
    github: GitHub, tag: str, files: list[Path], release: dict[str, Any]
) -> list[Path]:
    existing = asset_names(release)
    expected = {path.name for path in files}
    if len(expected) != len(files) or not existing <= expected:
        raise ValueError("unexpected or duplicate release assets")
    missing = [path for path in files if path.name not in existing]
    if missing and not release["draft"]:
        raise ValueError("published release is incomplete; refusing to mutate it")
    with tempfile.TemporaryDirectory() as temp:
        for path in files:
            if path.name in existing:
                downloaded = github.download(tag, path.name, Path(temp))
                if digest(downloaded) != digest(path):
                    raise ValueError(f"refusing to replace mismatched asset: {path.name}")
    return missing


def complete_draft(
    github: GitHub,
    tag: str,
    release: dict[str, Any],
    *,
    prerelease: bool,
    draft: bool,
    ci_exception: str,
) -> None:
    if ci_exception:
        body = str(release.get("body") or "")
        notice = (
            "## Testing status\n\n"
            f"This prerelease was published without requiring green CI. {ci_exception}\n\n"
            "The release build, package verification, and installer checks passed."
        )
        if notice not in body:
            with tempfile.TemporaryDirectory() as temp:
                notes = Path(temp) / "notes.md"
                notes.write_text(f"{notice}\n\n{body}", encoding="utf-8")
                github.command("edit", tag, "--notes-file", str(notes))
    github.command(
        "edit",
        tag,
        f"--prerelease={str(prerelease).lower()}",
        f"--draft={str(draft).lower()}",
        *(["--latest=false"] if prerelease else []),
    )


def check_publication_commit(
    github: GitHub, tag: str, sha: str, recheck: Callable[[], None] | None
) -> None:
    github.ensure_tag(tag, sha)
    if recheck:
        recheck()


def publish(
    github: GitHub,
    tag: str,
    files: list[Path],
    *,
    sha: str,
    prerelease: bool = False,
    draft: bool = False,
    recheck: Callable[[], None] | None = None,
    ci_exception: str = "",
) -> None:
    if not files or any(not path.is_file() or not path.stat().st_size for path in files):
        raise ValueError("missing or empty publication files")
    if ci_exception and not prerelease:
        raise ValueError("stable releases cannot use a CI exception")
    check_publication_commit(github, tag, sha, recheck)
    release = github.release(tag)
    if release is None:
        github.command("create", tag, "--draft", "--verify-tag", "--title", tag, "--generate-notes")
        release = github.release(tag)
    if release is None:
        raise RuntimeError("release creation did not return a draft")
    if not release["draft"] and (draft or release["prerelease"] != prerelease):
        raise ValueError("refusing to change published release metadata")
    missing = missing_files(github, tag, files, release)
    if missing:
        github.command("upload", tag, *(str(path) for path in missing))
    final = github.release(tag)
    if final is None or asset_names(final) != {path.name for path in files}:
        raise ValueError("release asset set is incomplete after upload")
    check_publication_commit(github, tag, sha, recheck)
    if release["draft"]:
        complete_draft(
            github,
            tag,
            final,
            prerelease=prerelease,
            draft=draft,
            ci_exception=ci_exception,
        )
