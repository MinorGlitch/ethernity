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
$ExpectedBundles = @(
    "recovery_kit.bundle.html",
    "recovery_kit.scanner.bundle.html"
)

if (-not (Get-Command libdeflate-gzip -ErrorAction SilentlyContinue)) {
    throw "libdeflate-gzip is required to generate deterministic recovery-kit bundles"
}

Get-ChildItem -Path $KitResourceDir -Filter "recovery_kit*.bundle.html" -File `
    -ErrorAction SilentlyContinue | Remove-Item -Force

Push-Location kit
try {
    npm ci
    $env:ETHERNITY_KIT_COMPRESSION = "gzip"
    $env:ETHERNITY_KIT_VARIANTS = "both"
    node build_kit.mjs
}
finally {
    Remove-Item Env:ETHERNITY_KIT_COMPRESSION -ErrorAction SilentlyContinue
    Remove-Item Env:ETHERNITY_KIT_VARIANTS -ErrorAction SilentlyContinue
    Pop-Location
}

$GeneratedBundles = @(Get-ChildItem -Path $KitResourceDir -Filter "*.html" -File)
if ($GeneratedBundles.Count -ne $ExpectedBundles.Count) {
    $GeneratedNames = ($GeneratedBundles | ForEach-Object Name) -join ", "
    throw "Expected exactly $($ExpectedBundles.Count) generated recovery-kit bundles; found: $GeneratedNames"
}
foreach ($BundleName in $ExpectedBundles) {
    $BundlePath = Join-Path $KitResourceDir $BundleName
    $Bundle = Get-Item $BundlePath -ErrorAction SilentlyContinue
    if ($null -eq $Bundle -or $Bundle.Length -eq 0) {
        throw "Missing or empty generated recovery-kit bundle: $BundlePath"
    }
}

uv sync --extra build --frozen
uv run pyinstaller --clean --noconfirm ethernity.spec
