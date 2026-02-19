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
import tomllib
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


def _normalize_package_name(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def _sha256_from_lock_hash(value: str) -> str:
    prefix = "sha256:"
    if value.startswith(prefix):
        return value[len(prefix) :]
    return value


def _wheel_filename(wheel: dict[str, object]) -> str:
    url = str(wheel["url"])
    return url.rsplit("/", 1)[-1]


def _choose_wheel(package: dict[str, object], predicate: str) -> dict[str, object] | None:
    wheels = package.get("wheels", [])
    if not isinstance(wheels, list):
        return None
    matches: list[dict[str, object]] = []
    for wheel in wheels:
        if not isinstance(wheel, dict):
            continue
        filename = _wheel_filename(wheel)
        if re.search(predicate, filename):
            matches.append(wheel)
    if not matches:
        return None
    matches.sort(key=lambda wheel: ("cp313" not in _wheel_filename(wheel), _wheel_filename(wheel)))
    return matches[0]


def _choose_artifact_for_block(
    package: dict[str, object], current_url: str
) -> tuple[str, str] | None:
    sdist = package.get("sdist")
    if current_url.endswith(".tar.gz"):
        if isinstance(sdist, dict):
            return str(sdist["url"]), _sha256_from_lock_hash(str(sdist["hash"]))
        return None

    wheel: dict[str, object] | None
    if "none-any.whl" in current_url:
        wheel = _choose_wheel(package, r"none-any\.whl$")
    elif "macosx" in current_url and "universal2" in current_url:
        wheel = _choose_wheel(package, r"macosx.*universal2|universal2.*macosx")
        if wheel is None:
            wheel = _choose_wheel(package, r"macosx")
    elif "macosx" in current_url and "arm64" in current_url:
        wheel = _choose_wheel(package, r"macosx.*arm64|arm64.*macosx")
        if wheel is None:
            wheel = _choose_wheel(package, r"macosx.*universal2|universal2.*macosx")
    elif "macosx" in current_url and "x86_64" in current_url:
        wheel = _choose_wheel(package, r"macosx.*x86_64|x86_64.*macosx")
        if wheel is None:
            wheel = _choose_wheel(package, r"macosx.*universal2|universal2.*macosx")
    elif "macosx" in current_url:
        wheel = _choose_wheel(package, r"macosx.*universal2|universal2.*macosx")
        if wheel is None:
            wheel = _choose_wheel(package, r"macosx")
    elif "manylinux" in current_url and ("aarch64" in current_url or "arm64" in current_url):
        wheel = _choose_wheel(package, r"manylinux.*aarch64|aarch64.*manylinux")
    elif "manylinux" in current_url and "x86_64" in current_url:
        wheel = _choose_wheel(package, r"manylinux.*x86_64|x86_64.*manylinux")
    elif "aarch64" in current_url or "arm64" in current_url:
        wheel = _choose_wheel(package, r"aarch64|arm64")
    elif "x86_64" in current_url:
        wheel = _choose_wheel(package, r"x86_64")
    else:
        wheel = _choose_wheel(package, r"\.whl$")

    if wheel is None:
        if isinstance(sdist, dict):
            return str(sdist["url"]), _sha256_from_lock_hash(str(sdist["hash"]))
        return None
    return str(wheel["url"]), _sha256_from_lock_hash(str(wheel["hash"]))


def _load_lock_packages(lock_path: Path) -> dict[str, dict[str, object]]:
    data = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    packages = data.get("package")
    if not isinstance(packages, list):
        raise ValueError("uv.lock does not contain a package list")
    by_name: dict[str, dict[str, object]] = {}
    for package in packages:
        if not isinstance(package, dict):
            continue
        name_value = package.get("name")
        if not isinstance(name_value, str):
            continue
        by_name[_normalize_package_name(name_value)] = package
    return by_name


def _render_resources_from_lock(formula: str, lock_packages: dict[str, dict[str, object]]) -> str:
    lines = formula.splitlines(keepends=True)
    index = 0
    while index < len(lines):
        match = re.match(r'\s*resource "([^"]+)" do\s*$', lines[index])
        if not match:
            index += 1
            continue

        package_name = _normalize_package_name(match.group(1))
        package = lock_packages.get(package_name)
        if package is None:
            index += 1
            continue

        block_end = index + 1
        url_idx = None
        sha_idx = None
        while block_end < len(lines):
            stripped = lines[block_end].strip()
            if stripped.startswith('url "') and url_idx is None:
                url_idx = block_end
            elif stripped.startswith('sha256 "') and sha_idx is None:
                sha_idx = block_end
            elif stripped == "end":
                break
            block_end += 1

        if url_idx is None or sha_idx is None or block_end >= len(lines):
            index = block_end + 1
            continue

        current_url_match = re.search(r'url "([^"]+)"', lines[url_idx])
        if current_url_match is None:
            index = block_end + 1
            continue
        current_url = current_url_match.group(1)
        selected = _choose_artifact_for_block(package, current_url)
        if selected is not None:
            new_url, new_sha = selected
            url_indent = lines[url_idx][: len(lines[url_idx]) - len(lines[url_idx].lstrip())]
            sha_indent = lines[sha_idx][: len(lines[sha_idx]) - len(lines[sha_idx].lstrip())]
            lines[url_idx] = f'{url_indent}url "{new_url}"\n'
            lines[sha_idx] = f'{sha_indent}sha256 "{new_sha}"\n'

        index = block_end + 1

    return "".join(lines)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate source-based Homebrew formula from template."
    )
    parser.add_argument("--repo", required=True, help="GitHub repository slug (owner/name).")
    parser.add_argument("--tag", required=True, help="Release tag (e.g. v0.2.1).")
    parser.add_argument("--template", required=True, help="Path to formula template file.")
    parser.add_argument("--output", required=True, help="Output formula file path.")
    parser.add_argument("--lock", default="uv.lock", help="Path to uv.lock dependency lockfile.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    tag = _normalize_tag(args.tag)
    template_path = Path(args.template)
    output_path = Path(args.output)
    lock_path = Path(args.lock)
    source_url = f"https://github.com/{args.repo}/archive/refs/tags/{tag}.tar.gz"
    source_sha = _sha256_from_url(source_url)

    template = template_path.read_text(encoding="utf-8")
    rendered = _render_formula(template, source_url, source_sha)
    rendered = _render_resources_from_lock(rendered, _load_lock_packages(lock_path))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    print(f"Wrote source formula to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
