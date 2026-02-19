#!/usr/bin/env python3
# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

import argparse
import hashlib
import urllib.request
from pathlib import Path


def _normalize_tag(tag: str) -> str:
    value = tag.strip()
    if not value:
        raise ValueError("tag must be non-empty")
    if value.startswith("refs/tags/"):
        return value.removeprefix("refs/tags/")
    return value


def _sha256_from_url(url: str) -> str:
    hasher = hashlib.sha256()
    request = urllib.request.Request(
        url, headers={"User-Agent": "ethernity-homebrew-source-formula-generator"}
    )
    with urllib.request.urlopen(request) as response:  # nosec: B310 - fixed GitHub release URL
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _render_formula(template: str, source_url: str, source_sha: str) -> str:
    lines = template.splitlines(keepends=True)
    replaced = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('url "') and "/archive/refs/tags/" in stripped:
            lines[index] = f'  url "{source_url}"\n'
            next_index = index + 1
            while next_index < len(lines) and not lines[next_index].strip():
                next_index += 1
            if next_index >= len(lines) or not lines[next_index].strip().startswith('sha256 "'):
                raise ValueError("template does not contain a top-level sha256 line after url")
            lines[next_index] = f'  sha256 "{source_sha}"\n'
            replaced = True
            break
    if not replaced:
        raise ValueError("template does not contain a top-level source url line")
    return "".join(lines)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate source-based Homebrew formula from template."
    )
    parser.add_argument("--repo", required=True, help="GitHub repository slug (owner/name).")
    parser.add_argument("--tag", required=True, help="Release tag (e.g. v0.2.1).")
    parser.add_argument("--template", required=True, help="Path to formula template file.")
    parser.add_argument("--output", required=True, help="Output formula file path.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    tag = _normalize_tag(args.tag)
    template_path = Path(args.template)
    output_path = Path(args.output)
    source_url = f"https://github.com/{args.repo}/archive/refs/tags/{tag}.tar.gz"
    source_sha = _sha256_from_url(source_url)

    template = template_path.read_text(encoding="utf-8")
    rendered = _render_formula(template, source_url, source_sha)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    print(f"Wrote source formula to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
