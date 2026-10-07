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

rm -f "${KIT_RESOURCE_DIR}"/recovery_kit*.bundle.html
(
  cd kit
  npm ci
  ETHERNITY_KIT_COMPRESSION=gzip ETHERNITY_KIT_VARIANTS=both node build_kit.mjs
)

uv sync --extra build --frozen
uv run python -m tooling.release_resources --kit-directory "${KIT_RESOURCE_DIR}"
uv run pyinstaller --clean --noconfirm ethernity.spec
