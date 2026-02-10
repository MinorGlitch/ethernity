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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
OUTPUT_DIR="${NUITKA_OUTPUT_DIR:-${PROJECT_ROOT}/dist/nuitka}"
NUITKA_PYTHON="${NUITKA_PYTHON:-3.13}"

cd "${PROJECT_ROOT}"

has_mode=0
has_module_flag=0
args=("$@")
for ((i = 0; i < ${#args[@]}; i++)); do
    arg="${args[i]}"
    if [[ \
        "${arg}" == "--standalone" || \
        "${arg}" == "--onefile" || \
        "${arg}" == "--mode" || \
        "${arg}" == --mode=* \
    ]]; then
        has_mode=1
    fi

    if [[ "${arg}" == "--python-flag=-m" ]]; then
        has_module_flag=1
    fi
    if [[ \
        "${arg}" == "--python-flag" && \
        $((i + 1)) -lt ${#args[@]} && \
        "${args[i + 1]}" == "-m" \
    ]]; then
        has_module_flag=1
    fi
done

if [[ -n "${PYTHONPATH:-}" ]]; then
    export PYTHONPATH="${PROJECT_ROOT}/src:${PYTHONPATH}"
else
    export PYTHONPATH="${PROJECT_ROOT}/src"
fi

mkdir -p "${OUTPUT_DIR}"

nuitka_cmd=(
    uv run --python "${NUITKA_PYTHON}" --with nuitka --with zstandard python -m nuitka
)
if [[ ${has_mode} -eq 0 ]]; then
    nuitka_cmd+=(--standalone)
fi
if [[ ${has_module_flag} -eq 0 ]]; then
    nuitka_cmd+=(--python-flag=-m)
fi
nuitka_cmd+=(
    --assume-yes-for-downloads
    --remove-output
    --output-dir="${OUTPUT_DIR}"
    --output-filename=ethernity
    --include-package=playwright
    --include-package=questionary
    --include-package=prompt_toolkit
    --include-package-data=ethernity
    --noinclude-data-files=playwright/driver/node
    --noinclude-data-files=playwright/driver/node.exe
)
nuitka_cmd+=("$@")
nuitka_cmd+=("${PROJECT_ROOT}/src/ethernity")

"${nuitka_cmd[@]}"
