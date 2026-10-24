"""Select packaging rehearsals without skipping any existing test job."""

from __future__ import annotations

import json
import os
import sys
import tomllib
from pathlib import Path
from typing import Any

from tooling.release.github import output, run

HOMEBREW_INPUTS = (".github/", "tooling/release", "scripts/", "src/ethernity/resources/")
PACKAGE_FILES = {"pyproject.toml", "uv.lock", "MANIFEST.in", "ethernity.spec"}


def packaging_changes(paths: list[str]) -> tuple[bool, bool]:
    native = any(not (path.endswith(".md") or path.startswith("docs/")) for path in paths)
    homebrew = any(path in PACKAGE_FILES or path.startswith(HOMEBREW_INPUTS) for path in paths)
    return native, homebrew


def failures(needs: dict[str, Any]) -> list[str]:
    selection = needs["kit-bundles"].get("outputs", {})
    optional_jobs = {"native-packages": "native", "homebrew-rehearsal": "homebrew"}
    allowed_skips = {
        job for job, flag in optional_jobs.items() if selection.get(flag, "true") == "false"
    }
    return [
        name
        for name, job in needs.items()
        if job["result"] != "success" and not (name in allowed_skips and job["result"] == "skipped")
    ]


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "gate":
        failed = failures(json.loads(os.environ["NEEDS_CONTEXT"]))
        if failed:
            raise SystemExit(f"Required CI jobs did not succeed: {', '.join(failed)}")
        print("All required CI jobs succeeded.")
        return
    native, homebrew = True, True
    if os.environ["GITHUB_EVENT_NAME"] == "pull_request":
        paths = run("git", "diff", "--name-only", os.environ["BASE_SHA"], "HEAD").splitlines()
        native, homebrew = packaging_changes(paths)
    version = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    output(tag=f"v{version}", native=json.dumps(native), homebrew=json.dumps(homebrew))


if __name__ == "__main__":
    main()
