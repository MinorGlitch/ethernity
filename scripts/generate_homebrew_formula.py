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
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RELEASE_API_TEMPLATE = "https://api.github.com/repos/{repo}/releases/tags/{tag}"
ASSET_MATRIX = (
    ("macos", "arm64"),
    ("macos", "x64"),
    ("linux", "arm64"),
    ("linux", "x64"),
)
FORMULA_HEADER = """class Ethernity < Formula
  desc "Secure, offline-recoverable backup system with QR-based recovery documents"
  homepage "https://github.com/MinorGlitch/ethernity"
  license "GPL-3.0-or-later"
  version "{version}"

"""


@dataclass(frozen=True)
class TargetAsset:
    os_name: str
    arch: str
    url: str
    sha256: str


def _request_json(url: str, token: str | None) -> dict[str, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ethernity-homebrew-formula-generator",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request) as response:  # nosec: B310 - fixed GitHub API URL
        payload = response.read()
    return json.loads(payload.decode("utf-8"))


def _sha256_from_url(url: str) -> str:
    hasher = hashlib.sha256()
    request = urllib.request.Request(
        url, headers={"User-Agent": "ethernity-homebrew-formula-generator"}
    )
    with urllib.request.urlopen(request) as response:  # nosec: B310 - validated release URL
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _sha256_from_asset(asset: dict[str, Any]) -> str:
    digest = str(asset.get("digest", "")).strip()
    if digest.startswith("sha256:"):
        return digest.split(":", 1)[1].lower()
    url = str(asset.get("browser_download_url", "")).strip()
    if not url:
        raise ValueError(f"asset is missing browser_download_url: {asset.get('name', '<unknown>')}")
    return _sha256_from_url(url)


def _normalize_tag(tag: str) -> str:
    value = tag.strip()
    if not value:
        raise ValueError("tag must be non-empty")
    if value.startswith("refs/tags/"):
        return value.removeprefix("refs/tags/")
    return value


def _version_from_tag(tag: str) -> str:
    if tag.startswith("v") and len(tag) > 1:
        return tag[1:]
    return tag


def _find_asset(
    assets_by_name: dict[str, dict[str, Any]], tag: str, os_name: str, arch: str
) -> TargetAsset:
    name = f"ethernity-{tag}-{os_name}-{arch}.tar.gz"
    asset = assets_by_name.get(name)
    if asset is None:
        raise ValueError(f"release is missing required asset: {name}")
    url = str(asset.get("browser_download_url", "")).strip()
    if not url:
        raise ValueError(f"asset {name} has no browser_download_url")
    sha256 = _sha256_from_asset(asset)
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise ValueError(f"invalid sha256 for {name}: {sha256!r}")
    return TargetAsset(os_name=os_name, arch=arch, url=url, sha256=sha256)


def _build_formula(version: str, target_assets: dict[tuple[str, str], TargetAsset]) -> str:
    mac_arm = target_assets[("macos", "arm64")]
    mac_x64 = target_assets[("macos", "x64")]
    linux_arm = target_assets[("linux", "arm64")]
    linux_x64 = target_assets[("linux", "x64")]
    return (
        FORMULA_HEADER.format(version=version)
        + "  on_macos do\n"
        + "    if Hardware::CPU.arm?\n"
        + f'      url "{mac_arm.url}"\n'
        + f'      sha256 "{mac_arm.sha256}"\n'
        + "    else\n"
        + f'      url "{mac_x64.url}"\n'
        + f'      sha256 "{mac_x64.sha256}"\n'
        + "    end\n"
        + "  end\n\n"
        + "  on_linux do\n"
        + "    if Hardware::CPU.arm?\n"
        + f'      url "{linux_arm.url}"\n'
        + f'      sha256 "{linux_arm.sha256}"\n'
        + "    else\n"
        + f'      url "{linux_x64.url}"\n'
        + f'      sha256 "{linux_x64.sha256}"\n'
        + "    end\n"
        + "  end\n\n"
        + "  def install\n"
        + '    bundle_dir = Dir["ethernity-v#{version}-*"]&.first\n'
        + '    raise "Unable to locate extracted release bundle" if bundle_dir.nil?\n\n'
        + '    libexec.install Dir["#{bundle_dir}/*"]\n'
        + '    bin.install_symlink libexec/"ethernity"\n'
        + "  end\n\n"
        + "  test do\n"
        + '    env "ETHERNITY_SKIP_PLAYWRIGHT_INSTALL", "1"\n'
        + '    assert_match "Usage", shell_output("#{bin}/ethernity --help")\n'
        + "  end\n"
        + "end\n"
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Homebrew formula for Ethernity from release assets."
    )
    parser.add_argument("--repo", required=True, help="GitHub repository slug (owner/name).")
    parser.add_argument("--tag", required=True, help="Release tag (e.g. v0.2.1).")
    parser.add_argument("--output", required=True, help="Output file path.")
    parser.add_argument(
        "--token-env",
        default="GITHUB_TOKEN",
        help="Environment variable name containing GitHub token (default: GITHUB_TOKEN).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    tag = _normalize_tag(args.tag)
    version = _version_from_tag(tag)
    token = os.environ.get(args.token_env, "").strip() or None
    url = RELEASE_API_TEMPLATE.format(repo=args.repo, tag=tag)

    try:
        release = _request_json(url, token)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise SystemExit(f"failed to fetch release metadata: {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"failed to fetch release metadata: {exc.reason}") from exc

    assets = release.get("assets")
    if not isinstance(assets, list):
        raise SystemExit("release payload is missing assets list")
    assets_by_name = {str(asset.get("name", "")): asset for asset in assets}

    resolved: dict[tuple[str, str], TargetAsset] = {}
    for os_name, arch in ASSET_MATRIX:
        resolved[(os_name, arch)] = _find_asset(assets_by_name, tag, os_name, arch)

    formula = _build_formula(version, resolved)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(formula, encoding="utf-8")
    print(f"Wrote formula to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
