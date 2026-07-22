#!/usr/bin/env bash
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

set -euo pipefail

KIT_RESOURCE_DIR="src/ethernity/resources/kit"
EXPECTED_BUNDLES=(
  "recovery_kit.bundle.html"
  "recovery_kit.scanner.bundle.html"
)

if ! command -v libdeflate-gzip >/dev/null 2>&1; then
  echo "libdeflate-gzip is required to generate deterministic recovery-kit bundles" >&2
  exit 1
fi

rm -f "${KIT_RESOURCE_DIR}"/recovery_kit*.bundle.html
(
  cd kit
  npm ci
  ETHERNITY_KIT_COMPRESSION=gzip ETHERNITY_KIT_VARIANTS=both node build_kit.mjs
)

shopt -s nullglob
generated_bundles=("${KIT_RESOURCE_DIR}"/*.html)
if (( ${#generated_bundles[@]} != ${#EXPECTED_BUNDLES[@]} )); then
  echo "expected exactly ${#EXPECTED_BUNDLES[@]} generated recovery-kit bundles" >&2
  printf '  %s\n' "${generated_bundles[@]}" >&2
  exit 1
fi
for bundle_name in "${EXPECTED_BUNDLES[@]}"; do
  bundle_path="${KIT_RESOURCE_DIR}/${bundle_name}"
  if [[ ! -s "${bundle_path}" ]]; then
    echo "missing or empty generated recovery-kit bundle: ${bundle_path}" >&2
    exit 1
  fi
done

uv sync --extra build --frozen
uv run pyinstaller --clean --noconfirm ethernity.spec
