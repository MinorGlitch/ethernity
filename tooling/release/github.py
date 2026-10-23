"""Small gh adapter shared by binary and Homebrew publication."""

from __future__ import annotations

import json
import os
import subprocess
import urllib.parse
from pathlib import Path
from typing import Any


def run(*args: str, cwd: Path | None = None) -> str:
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def output(**values: str) -> None:
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
        for name, value in values.items():
            if "\n" in value or "\r" in value:
                raise ValueError("multiline workflow output")
            stream.write(f"{name}={value}\n")


class GitHub:
    def __init__(self, repo: str) -> None:
        self.repo = repo

    def api(self, path: str, *, fields: dict[str, str] | None = None) -> Any:
        args = ["gh", "api", f"repos/{self.repo}/{path}"]
        for name, value in (fields or {}).items():
            args.extend(["-f", f"{name}={value}"])
        return json.loads(run(*args) or "null")

    def release(self, tag: str) -> dict[str, Any] | None:
        # Only a confirmed 404 means absent. Auth, rate-limit and network errors must fail.
        result = subprocess.run(
            ["gh", "api", f"repos/{self.repo}/releases/tags/{urllib.parse.quote(tag, safe='')}"],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
        if "(HTTP 404)" in result.stderr:
            # The tag endpoint returns published releases only. Drafts are visible
            # through the authenticated list endpoint, including on later pages.
            pages = json.loads(
                run(
                    "gh", "api", f"repos/{self.repo}/releases?per_page=100", "--paginate", "--slurp"
                )
            )
            matches = [release for page in pages for release in page if release["tag_name"] == tag]
            if len(matches) > 1:
                raise ValueError(f"multiple releases found for tag {tag}")
            if matches:
                return matches[0]
            return None
        raise RuntimeError(result.stderr)

    def tag_sha(self, tag: str) -> str | None:
        lines = run(
            "git",
            "ls-remote",
            f"https://github.com/{self.repo}.git",
            f"refs/tags/{tag}",
            f"refs/tags/{tag}^{{}}",
        )
        refs = dict(line.split()[::-1] for line in lines.splitlines())
        return refs.get(f"refs/tags/{tag}^{{}}", refs.get(f"refs/tags/{tag}"))

    def ensure_tag(self, tag: str, sha: str, *, create: bool = False) -> None:
        current = self.tag_sha(tag)
        if current is None and create:
            self.api("git/refs", fields={"ref": f"refs/tags/{tag}", "sha": sha})
            current = self.tag_sha(tag)
        if current != sha:
            raise ValueError(f"tag {tag} changed or is missing: expected {sha}, found {current}")

    def download(self, tag: str, name: str, directory: Path) -> Path:
        if Path(name).name != name or name in {".", ".."}:
            raise ValueError(f"invalid asset name: {name}")
        run(
            "gh",
            "release",
            "download",
            tag,
            "--repo",
            self.repo,
            "--pattern",
            name,
            "--dir",
            str(directory),
        )
        return directory / name

    def command(self, *args: str) -> str:
        return run("gh", "release", *args, "--repo", self.repo)
