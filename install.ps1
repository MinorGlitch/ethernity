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

[CmdletBinding()]
param(
    [string]$Version,
    [string]$InstallRoot = "$env:LOCALAPPDATA\Programs\Ethernity",
    [switch]$SkipVerify,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$RepoOwner = "MinorGlitch"
$RepoName = "ethernity"
$UserAgent = "Ethernity-Windows-Installer"

function Write-Step {
    param([string]$Message)
    Write-Host ("==> {0}" -f $Message) -ForegroundColor Cyan
}

function Get-ReleaseMetadata {
    param([string]$RequestedVersion)

    $headers = @{ "User-Agent" = $UserAgent }
    if ([string]::IsNullOrWhiteSpace($RequestedVersion)) {
        $uri = "https://api.github.com/repos/$RepoOwner/$RepoName/releases/latest"
        return Invoke-RestMethod -Uri $uri -Headers $headers
    }

    $normalized = $RequestedVersion.Trim()
    if (-not $normalized.StartsWith("v")) {
        $normalized = "v$normalized"
    }
    $uri = "https://api.github.com/repos/$RepoOwner/$RepoName/releases/tags/$normalized"
    return Invoke-RestMethod -Uri $uri -Headers $headers
}

function Get-Asset {
    param(
        [object]$Release,
        [string]$Name
    )

    $asset = $Release.assets | Where-Object { $_.name -eq $Name } | Select-Object -First 1
    if ($null -eq $asset) {
        throw "Release $($Release.tag_name) does not contain asset '$Name'."
    }
    return $asset
}

function Get-PreferredArtifactArch {
    param([object]$Release)

    $available = @($Release.assets | ForEach-Object { [string]$_.name })
    $candidates = @("windows-arm64", "windows-x64")
    foreach ($candidate in $candidates) {
        if ($available -match ("-{0}\.zip$" -f [regex]::Escape($candidate))) {
            if ($candidate -eq "windows-arm64") {
                try {
                    $osArch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture
                    if ($osArch.ToString().ToUpperInvariant() -eq "ARM64") {
                        return $candidate
                    }
                }
                catch {
                    continue
                }
                continue
            }
            return $candidate
        }
    }
    throw "No supported Windows release asset was found."
}

function Invoke-Download {
    param(
        [string]$Uri,
        [string]$Destination
    )

    Invoke-WebRequest -Uri $Uri -OutFile $Destination -Headers @{ "User-Agent" = $UserAgent }
}

function Ensure-UserPathContains {
    param([string]$PathEntry)

    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $entries = @()
    if (-not [string]::IsNullOrWhiteSpace($userPath)) {
        $entries = $userPath.Split(";", [System.StringSplitOptions]::RemoveEmptyEntries)
    }

    $alreadyPresent = $entries | Where-Object { $_.TrimEnd("\\") -ieq $PathEntry.TrimEnd("\\") }
    if ($alreadyPresent) {
        return $false
    }

    $newEntries = @($entries + $PathEntry)
    [Environment]::SetEnvironmentVariable("Path", ($newEntries -join ";"), "User")
    return $true
}

function Invoke-CosignVerify {
    param(
        [string]$ArchivePath,
        [string]$BundlePath
    )

    $cosign = Get-Command cosign -ErrorAction SilentlyContinue
    if ($null -eq $cosign) {
        Write-Warning "cosign not found; skipping Sigstore verification."
        Write-Host "See the release verification guide if you want to verify manually:" -ForegroundColor Yellow
        Write-Host "https://github.com/MinorGlitch/ethernity/wiki/Release-Artifacts" -ForegroundColor Yellow
        return
    }

    Write-Step "Verifying release archive with cosign"
    & $cosign.Source verify-blob --bundle $BundlePath $ArchivePath
    if ($LASTEXITCODE -ne 0) {
        throw "cosign verification failed for $ArchivePath"
    }
}

Write-Step "Resolving release metadata"
$release = Get-ReleaseMetadata -RequestedVersion $Version
$tag = [string]$release.tag_name
if ([string]::IsNullOrWhiteSpace($tag)) {
    throw "Unable to determine release tag from GitHub API response."
}

$artifactArch = Get-PreferredArtifactArch -Release $release
$archiveName = "ethernity-$tag-$artifactArch.zip"
$bundleName = "$archiveName.sigstore.json"
$archiveAsset = Get-Asset -Release $release -Name $archiveName
$bundleAsset = Get-Asset -Release $release -Name $bundleName

$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("ethernity-install-" + [System.Guid]::NewGuid())
$downloadDir = Join-Path $tempRoot "download"
$extractDir = Join-Path $tempRoot "extract"
$archivePath = Join-Path $downloadDir $archiveName
$bundlePath = Join-Path $downloadDir $bundleName

New-Item -ItemType Directory -Path $downloadDir -Force | Out-Null
New-Item -ItemType Directory -Path $extractDir -Force | Out-Null

try {
    Write-Step "Downloading $archiveName"
    Invoke-Download -Uri $archiveAsset.browser_download_url -Destination $archivePath

    if (-not $SkipVerify) {
        Write-Step "Downloading Sigstore bundle"
        Invoke-Download -Uri $bundleAsset.browser_download_url -Destination $bundlePath
        Invoke-CosignVerify -ArchivePath $archivePath -BundlePath $bundlePath
    }

    Write-Step "Extracting archive"
    Expand-Archive -Path $archivePath -DestinationPath $extractDir -Force

    $extractedRoot = Get-ChildItem -Path $extractDir -Directory | Select-Object -First 1
    if ($null -eq $extractedRoot) {
        throw "Archive extraction did not produce an install directory."
    }

    $installRootResolved = [System.IO.Path]::GetFullPath($InstallRoot)
    $currentDir = Join-Path $installRootResolved "current"
    $versionFile = Join-Path $installRootResolved "installed-version.txt"

    if ((Test-Path $currentDir) -and -not $Force) {
        Write-Step "Replacing existing installation"
    }

    New-Item -ItemType Directory -Path $installRootResolved -Force | Out-Null
    if (Test-Path $currentDir) {
        Remove-Item -Path $currentDir -Recurse -Force
    }

    Move-Item -Path $extractedRoot.FullName -Destination $currentDir
    Set-Content -Path $versionFile -Value $tag -Encoding ascii

    $pathUpdated = Ensure-UserPathContains -PathEntry $currentDir
    $exePath = Join-Path $currentDir "ethernity.exe"
    if (-not (Test-Path $exePath)) {
        throw "Installation succeeded, but ethernity.exe was not found at $exePath"
    }

    Write-Host ""
    Write-Host "Ethernity installed successfully." -ForegroundColor Green
    Write-Host ("Version: {0}" -f $tag)
    Write-Host ("Path:    {0}" -f $exePath)
    if ($pathUpdated) {
        Write-Host "User PATH updated. Restart your terminal before running 'ethernity'." -ForegroundColor Yellow
    }
    else {
        Write-Host "You can run 'ethernity --help' in a new terminal." -ForegroundColor Green
    }
}
finally {
    if (Test-Path $tempRoot) {
        Remove-Item -Path $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
