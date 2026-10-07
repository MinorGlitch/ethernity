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

$ErrorActionPreference = "Stop"

$KitResourceDir = "src/ethernity/resources/kit"

Get-ChildItem -Path $KitResourceDir -Filter "recovery_kit*.bundle.html" -File `
    -ErrorAction SilentlyContinue | Remove-Item -Force

Push-Location kit
try {
    npm ci
    if ($LASTEXITCODE -ne 0) { throw "Kit dependency installation failed" }
    $env:ETHERNITY_KIT_COMPRESSION = "gzip"
    $env:ETHERNITY_KIT_VARIANTS = "both"
    node build_kit.mjs
    if ($LASTEXITCODE -ne 0) { throw "Recovery-kit generation failed" }
}
finally {
    Remove-Item Env:ETHERNITY_KIT_COMPRESSION -ErrorAction SilentlyContinue
    Remove-Item Env:ETHERNITY_KIT_VARIANTS -ErrorAction SilentlyContinue
    Pop-Location
}

uv sync --extra build --frozen
if ($LASTEXITCODE -ne 0) { throw "Build dependency installation failed" }
uv run python -m tooling.release_resources --kit-directory $KitResourceDir
if ($LASTEXITCODE -ne 0) { throw "Recovery-kit bundle verification failed" }
uv run pyinstaller --clean --noconfirm ethernity.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }
