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

param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$NuitkaArgs
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..")
$OutputDir = if ($env:NUITKA_OUTPUT_DIR) { $env:NUITKA_OUTPUT_DIR } else { Join-Path $ProjectRoot "dist/nuitka" }
$NuitkaPython = if ($env:NUITKA_PYTHON) { $env:NUITKA_PYTHON } else { "3.13" }

$hasMode = $false
$hasModuleFlag = $false
for ($i = 0; $i -lt $NuitkaArgs.Count; $i++) {
    $arg = $NuitkaArgs[$i]
    if (
        $arg -eq "--standalone" -or
        $arg -eq "--onefile" -or
        $arg -eq "--mode" -or
        $arg -like "--mode=*"
    ) {
        $hasMode = $true
    }

    if ($arg -eq "--python-flag=-m") {
        $hasModuleFlag = $true
    }
    if (
        $arg -eq "--python-flag" -and
        ($i + 1) -lt $NuitkaArgs.Count -and
        $NuitkaArgs[$i + 1] -eq "-m"
    ) {
        $hasModuleFlag = $true
    }
}

$modeArgs = @()
if (-not $hasMode) {
    $modeArgs += "--standalone"
}
$moduleModeArgs = @()
if (-not $hasModuleFlag) {
    $moduleModeArgs += "--python-flag=-m"
}

$srcPath = Join-Path $ProjectRoot "src"
if ([string]::IsNullOrWhiteSpace($env:PYTHONPATH)) {
    $env:PYTHONPATH = $srcPath
} else {
    $env:PYTHONPATH = "$srcPath;$($env:PYTHONPATH)"
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$mainPackage = Join-Path $ProjectRoot "src/ethernity"

uv run --python "$NuitkaPython" --with nuitka --with zstandard python -m nuitka `
    @modeArgs `
    @moduleModeArgs `
    --assume-yes-for-downloads `
    --remove-output `
    --output-dir="$OutputDir" `
    --output-filename=ethernity `
    --include-package=playwright `
    --include-package=questionary `
    --include-package=prompt_toolkit `
    --include-package-data=ethernity `
    --noinclude-data-files=playwright/driver/node `
    --noinclude-data-files=playwright/driver/node.exe `
    @NuitkaArgs `
    "$mainPackage"
