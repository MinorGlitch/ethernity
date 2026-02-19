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
import re
from pathlib import Path

_BOTTLE_BLOCK_PATTERN = re.compile(r"(?ms)^  bottle do\n.*?^  end\n")
_BOTTLE_TAG_PATTERN = re.compile(r"^ethernity--.+\.(?P<tag>[^.]+)\.bottle\.tar\.gz$")


def _sha256_for_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _extract_bottle_tag(path: Path) -> str:
    match = _BOTTLE_TAG_PATTERN.match(path.name)
    if match is None:
        raise ValueError(f"unsupported bottle file name: {path.name}")
    return match.group("tag")


def _build_bottle_block(tap_repo: str, release_tag: str, bottle_files: list[Path]) -> str:
    if not bottle_files:
        raise ValueError("at least one bottle file is required")

    entries: dict[str, str] = {}
    for bottle_file in bottle_files:
        tag = _extract_bottle_tag(bottle_file)
        entries[tag] = _sha256_for_file(bottle_file)

    lines = [
        "  bottle do",
        f'    root_url "https://github.com/{tap_repo}/releases/download/{release_tag}"',
    ]
    for tag in sorted(entries):
        lines.append(f'    sha256 cellar: :any_skip_relocation, {tag}: "{entries[tag]}"')
    lines.append("  end")
    return "\n".join(lines) + "\n"


def _insert_or_replace_bottle_block(formula: str, bottle_block: str) -> str:
    if _BOTTLE_BLOCK_PATTERN.search(formula) is not None:
        return _BOTTLE_BLOCK_PATTERN.sub(bottle_block, formula, count=1)

    lines = formula.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.strip().startswith('license "'):
            lines.insert(index + 1, "\n" + bottle_block + "\n")
            return "".join(lines)
    raise ValueError("formula does not contain a top-level license line")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Insert or update Homebrew bottle block in a formula file."
    )
    parser.add_argument("--formula", required=True, help="Path to Formula/ethernity.rb")
    parser.add_argument("--tap-repo", required=True, help="Tap repository slug (owner/name).")
    parser.add_argument("--release-tag", required=True, help="Tap release tag for bottle assets.")
    parser.add_argument(
        "--bottle-file",
        action="append",
        default=[],
        help="Path to ethernity bottle tarball (repeat for multiple files).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    formula_path = Path(args.formula)
    bottle_files = [Path(value) for value in args.bottle_file]
    bottle_block = _build_bottle_block(args.tap_repo, args.release_tag, bottle_files)
    formula = formula_path.read_text(encoding="utf-8")
    updated = _insert_or_replace_bottle_block(formula, bottle_block)
    formula_path.write_text(updated, encoding="utf-8")
    print(f"Updated bottle block in {formula_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
