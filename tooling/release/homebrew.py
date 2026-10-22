"""Keep bottle provenance separate from the tap branch being updated."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from pathlib import Path

from tooling.release.github import GitHub, output, run
from tooling.release.publish import asset_names, digest, publish

MANIFEST = "publication.json"
FORMULA = "ethernity.rb"


def validate_payload(directory: Path, *, tag: str, source_sha: str) -> dict[str, str]:
    manifest = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
    if manifest["tag"] != tag or manifest["source_sha"] != source_sha:
        raise ValueError("bottle publication belongs to a different source release")
    files = manifest["files"]
    bottles = [name for name in files if re.fullmatch(r"ethernity--[^/\\]+\.bottle\.tar\.gz", name)]
    if len(bottles) != 2 or set(files) != {*bottles, FORMULA}:
        raise ValueError("publication must contain one formula and two bottles")
    actual = {path.name for path in directory.iterdir()}
    if actual != {*files, MANIFEST}:
        raise ValueError("unexpected or missing bottle publication files")
    for name, expected in files.items():
        if digest(directory / name) != expected:
            raise ValueError(f"bottle publication checksum mismatch: {name}")
    if not re.fullmatch(r"[a-f0-9]{40}", manifest["tap_base"]):
        raise ValueError("invalid bottle source commit")
    return manifest


def prepare(tap: GitHub, tag: str, source_sha: str, directory: Path) -> tuple[str, bool]:
    current_base = run(
        "git", "ls-remote", f"https://github.com/{tap.repo}.git", "refs/heads/master"
    ).split()[0]
    if not re.fullmatch(r"[a-f0-9]{40}", current_base):
        raise ValueError("cannot resolve tap master")
    release = tap.release(f"ethernity-{tag}")
    if release is None or release["draft"]:
        return current_base, False
    if release["prerelease"]:
        raise ValueError("bottle publication must be stable")
    directory.mkdir(parents=True, exist_ok=True)
    for name in asset_names(release):
        tap.download(f"ethernity-{tag}", name, directory)
    manifest = validate_payload(directory, tag=tag, source_sha=source_sha)
    tap.ensure_tag(f"ethernity-{tag}", manifest["tap_base"])
    return current_base, True


def assemble(
    directory: Path, formula: Path, bottles: Path, *, tag: str, source_sha: str, tap_base: str
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(formula, directory / FORMULA)
    paths = list(bottles.rglob("*.bottle.tar.gz"))
    if len(paths) != 2 or len({path.name for path in paths}) != 2:
        raise ValueError("expected two distinct bottle tarballs")
    for path in paths:
        shutil.copyfile(path, directory / path.name)
    files = {path.name: digest(path) for path in directory.iterdir()}
    manifest = {"tag": tag, "source_sha": source_sha, "tap_base": tap_base, "files": files}
    (directory / MANIFEST).write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    validate_payload(directory, tag=tag, source_sha=source_sha)


def publish_formula(checkout: Path, directory: Path, expected_base: str, tag: str) -> None:
    if run("git", "rev-parse", "HEAD", cwd=checkout) != expected_base:
        raise ValueError("tap changed since validation")
    destination = checkout / "Formula/ethernity.rb"
    current = destination.read_text(encoding="utf-8")
    match = re.search(r"/releases/download/v([0-9]+\.[0-9]+\.[0-9]+)/", current)
    if match and tuple(map(int, match[1].split("."))) > tuple(map(int, tag[1:].split("."))):
        raise ValueError("refusing to downgrade the tap to an older release")
    shutil.copyfile(directory / FORMULA, destination)
    run("git", "add", "Formula/ethernity.rb", cwd=checkout)
    if not run("git", "diff", "--cached", "--name-only", cwd=checkout):
        return
    run(
        "git",
        "-c",
        "user.name=github-actions[bot]",
        "-c",
        "user.email=41898282+github-actions[bot]@users.noreply.github.com",
        "commit",
        "-m",
        f"ethernity {tag}",
        cwd=checkout,
    )
    # Normal fast-forward push rejects a tap change after the initial check.
    run("git", "push", "origin", "HEAD:master", cwd=checkout)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "assemble", "publish"))
    args = parser.parse_args()
    tap = GitHub(os.environ["TAP_REPO"])
    tag = os.environ["RELEASE_TAG"]
    source_sha = os.environ["SOURCE_SHA"]
    directory = Path(os.environ["PUBLICATION_DIR"])
    if args.command == "prepare":
        base, reuse = prepare(tap, tag, source_sha, directory)
        output(expected_tap_base=base, reuse=str(reuse).lower())
    elif args.command == "assemble":
        assemble(
            directory,
            Path(os.environ["STAGE_DIR"]) / "Formula/ethernity.rb",
            Path(os.environ["BOTTLE_DIR"]),
            tag=tag,
            source_sha=source_sha,
            tap_base=os.environ["EXPECTED_TAP_BASE"],
        )
    else:
        manifest = validate_payload(directory, tag=tag, source_sha=source_sha)
        expected_base = os.environ["EXPECTED_TAP_BASE"]
        if run("git", "rev-parse", "HEAD", cwd=Path("tap")) != expected_base:
            raise ValueError("tap changed since validation")
        tap.ensure_tag(f"ethernity-{tag}", manifest["tap_base"], create=True)
        publish(tap, f"ethernity-{tag}", list(directory.iterdir()), sha=manifest["tap_base"])
        publish_formula(Path("tap"), directory, expected_base, tag)


if __name__ == "__main__":
    main()
