"""Resolve a release and require successful master push CI for its exact commit."""

from __future__ import annotations

import json
import os
import re
import time
import tomllib
import urllib.parse
from typing import Any

from tooling.release.github import GitHub, output, run
from tooling.release.inventory import release_files, validate_tag
from tooling.release.publish import asset_names


def check_master(tag: str, sha: str) -> None:
    run(
        "git",
        "fetch",
        "origin",
        f"refs/tags/{tag}",
        "+refs/heads/master:refs/remotes/origin/master",
    )
    if run("git", "rev-parse", "FETCH_HEAD^{commit}") != sha:
        raise ValueError("release tag changed during build")
    run("git", "merge-base", "--is-ancestor", sha, "refs/remotes/origin/master")


def ci_success(runs: list[dict[str, Any]], sha: str) -> bool:
    matching = [
        run
        for run in runs
        if run.get("event") == "push"
        and run.get("head_branch") == "master"
        and run.get("head_sha") == sha
    ]
    if not matching:
        return False
    latest = max(matching, key=lambda run: (run["run_number"], run.get("run_attempt", 1)))
    if latest["status"] != "completed":
        return False
    if latest["conclusion"] != "success":
        raise ValueError(f"latest master CI failed: {latest.get('html_url')}")
    return True


def wait_for_ci(github: GitHub, sha: str) -> None:
    query = urllib.parse.urlencode(
        {"branch": "master", "event": "push", "head_sha": sha, "per_page": 100}
    )
    deadline = time.monotonic() + 40 * 60
    while True:
        runs = github.api(f"actions/workflows/ci.yml/runs?{query}")["workflow_runs"]
        if ci_success(runs, sha):
            return
        if time.monotonic() >= deadline:
            raise TimeoutError("no successful master push CI for release commit")
        print(f"Waiting for master CI on {sha}", flush=True)
        time.sleep(20)


def published_release(github: GitHub, tag: str, *, draft: bool, prerelease: bool) -> bool:
    release = github.release(tag)
    if release is None or release["draft"]:
        return False
    if draft or release["prerelease"] != prerelease:
        raise ValueError("refusing to change published release metadata")
    if asset_names(release) != set(release_files(tag)):
        raise ValueError("published release has an incomplete or unexpected asset set")
    return True


def main() -> None:
    manual = os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch"
    if manual and os.environ["GITHUB_REF"] != "refs/heads/master":
        raise ValueError("manual releases must dispatch from master")
    tag = os.environ["REQUESTED_TAG"] if manual else os.environ["GITHUB_REF_NAME"]
    github = GitHub(os.environ["GITHUB_REPOSITORY"])
    sha = github.tag_sha(tag)
    if sha is None:
        raise ValueError("release tag is missing")
    check_master(tag, sha)
    project = tomllib.loads(run("git", "show", f"{sha}:pyproject.toml"))["project"]
    version = validate_tag(tag, project["version"])
    prerelease = version.is_prerelease or os.environ.get("REQUESTED_PRERELEASE") == "true"
    wait_for_ci(github, sha)
    draft = os.environ.get("REQUESTED_DRAFT") == "true"
    published = published_release(github, tag, draft=draft, prerelease=prerelease)
    homebrew = (
        not prerelease and not draft and re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag) is not None
    )
    output(
        tag=tag,
        commit_sha=sha,
        prerelease=json.dumps(prerelease),
        draft=json.dumps(draft),
        published=json.dumps(published),
        homebrew=json.dumps(homebrew),
    )


if __name__ == "__main__":
    main()
