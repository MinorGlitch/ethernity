# Copyright (C) 2026 Alex Stoyanov. GPL-3.0-or-later.
# Installs the complete Windows archive for the current user.
[CmdletBinding()]
param(
    [string]$Version = '',
    [string]$InstallRoot = "$env:LOCALAPPDATA\Programs\Ethernity",
    [string]$Archive,
    [string]$Checksums,
    [switch]$VerifySignature,
    [switch]$Uninstall
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Repo = 'https://github.com/MinorGlitch/ethernity'

function Download-File([string]$Uri, [string]$Destination) {
    Invoke-WebRequest -UseBasicParsing -Uri $Uri -OutFile $Destination
}
function Set-CommandPath([bool]$Remove) {
    $entries = @([Environment]::GetEnvironmentVariable('Path', 'User') -split ';' |
        Where-Object { $_ -and $_.TrimEnd('\') -ne $Current })
    if (-not $Remove) { $entries += $Current }
    [Environment]::SetEnvironmentVariable('Path', ($entries -join ';'), 'User')
}
function Assert-RealDirectory([string]$Path) {
    if ((Test-Path -LiteralPath $Path) -and
        ((Get-Item -LiteralPath $Path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Installation directories must not be links: $Path"
    }
}
function Confirm-Archive([string]$ZipPath, [string]$ChecksumPath, [string]$Name) {
    $entries = @(Get-Content -LiteralPath $ChecksumPath | Where-Object {
        $_ -cmatch ('^[a-fA-F0-9]{64}  ' + [regex]::Escape($Name) + '$')
    })
    if ($entries.Count -ne 1) { throw 'Archive is missing or duplicated in SHA256SUMS.' }
    $expected = $entries[0].Substring(0, 64)
    $stream = [IO.File]::OpenRead($ZipPath)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $actual = [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '') }
    finally { $sha.Dispose(); $stream.Dispose() }
    if ($actual -ne $expected) {
        throw 'Archive checksum does not match. Existing installation was kept.'
    }
}
function Expand-Release([string]$ZipPath, [string]$Destination, [string]$ExpectedRoot) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        foreach ($entry in $zip.Entries) {
            $name = $entry.FullName.Replace('\', '/')
            $mode = ($entry.ExternalAttributes -shr 16) -band 0xF000
            if (-not $name.StartsWith("$ExpectedRoot/", [StringComparison]::Ordinal) -or
                $name -match '(^|/)\.\.(/|$)|:' -or $mode -eq 0xA000) {
                throw "Unsafe ZIP entry: $name"
            }
        }
    }
    finally { $zip.Dispose() }
    [IO.Compression.ZipFile]::ExtractToDirectory($ZipPath, $Destination)
}

$InstallRoot = [IO.Path]::GetFullPath($InstallRoot).TrimEnd('\')
if ($InstallRoot -eq [IO.Path]::GetPathRoot($InstallRoot).TrimEnd('\') -or
    $InstallRoot -eq $env:USERPROFILE) { throw 'Choose a dedicated install directory.' }
$Current = Join-Path $InstallRoot 'current'
$Marker = Join-Path $InstallRoot '.ethernity-install'
$LegacyVersion = Join-Path $InstallRoot 'installed-version.txt'
Assert-RealDirectory $InstallRoot
Assert-RealDirectory $Current
if (Test-Path -LiteralPath $InstallRoot) {
    if (Test-Path -LiteralPath $Marker) {
        if ((Get-Content -Raw -LiteralPath $Marker).Trim() -ne 'ethernity-installer-v1') {
            throw 'Unknown installation marker.'
        }
    }
    elseif (-not ((Test-Path -LiteralPath $LegacyVersion) -and
        (Test-Path -LiteralPath (Join-Path $Current 'ethernity.exe')))) {
        throw "Not an Ethernity installation: $InstallRoot"
    }
}
elseif ($Uninstall) { Write-Host 'Ethernity is not installed here.'; exit 0 }
else {
    New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
    Set-Content -LiteralPath $Marker -Value 'ethernity-installer-v1' -Encoding ascii
}

$lockPath = Join-Path $InstallRoot '.install-lock'
try { $lock = [IO.File]::Open($lockPath, 'OpenOrCreate', 'ReadWrite', 'None') }
catch { throw 'Another installer is running. Wait for it to finish.' }
$stage = $null
$previous = $null
$replaced = $false
$committed = $false
$originalPath = [Environment]::GetEnvironmentVariable('Path', 'User')
try {
    if ($Uninstall) {
        Set-CommandPath $true
        if (Test-Path -LiteralPath $Current) { Remove-Item -LiteralPath $Current -Recurse -Force }
        foreach ($file in @($Marker, $LegacyVersion)) {
            if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file -Force }
        }
        $committed = $true
        Write-Host 'Ethernity uninstalled. Settings and backups were kept.'
    }
    else {
        # Windows ARM currently uses the tested x64 build via Windows emulation.
        # Do not advertise an unbuilt ARM archive or select by PowerShell process bitness.
        $osArch = $env:PROCESSOR_ARCHITEW6432
        if (-not $osArch) { $osArch = $env:PROCESSOR_ARCHITECTURE }
        if ($osArch -notin @('AMD64', 'ARM64')) { throw 'A 64-bit Windows system is required.' }
        if (-not $Version) {
            if ($Archive -or $Checksums) { throw 'Offline installation requires -Version.' }
            $release = Invoke-RestMethod -Uri 'https://api.github.com/repos/MinorGlitch/ethernity/releases/latest'
            $Version = $release.tag_name
        }
        $Version = $Version -replace '^v', ''
        if ($Version -notmatch '^[0-9][0-9A-Za-z._-]*$') { throw 'Use a release version such as 1.2.0.' }
        $tag = "v$Version"
        $stem = "ethernity-$tag-windows-x64"
        $name = "$stem.zip"
        $stage = Join-Path $InstallRoot ('.stage-' + [guid]::NewGuid())
        New-Item -ItemType Directory -Path $stage | Out-Null
        $zipPath = Join-Path $stage $name
        $checksumPath = Join-Path $stage 'SHA256SUMS'
        if ($Archive -or $Checksums) {
            if (-not $Archive -or -not $Checksums) { throw 'Supply both -Archive and -Checksums.' }
            if ($VerifySignature) { throw 'Verify Sigstore before offline installation. -VerifySignature requires online downloads.' }
            Copy-Item -LiteralPath $Archive -Destination $zipPath
            Copy-Item -LiteralPath $Checksums -Destination $checksumPath
        }
        else {
            Download-File "$Repo/releases/download/$tag/$name" $zipPath
            Download-File "$Repo/releases/download/$tag/SHA256SUMS" $checksumPath
        }
        Confirm-Archive $zipPath $checksumPath $name
        if ($VerifySignature) {
            $cosign = Get-Command cosign -ErrorAction Stop
            $bundle = Join-Path $stage 'bundle.json'
            Download-File "$Repo/releases/download/$tag/$name.sigstore.json" $bundle
            $branchIdentity = 'master'
            if ($Version -cmatch '^[0-9]+\.[0-9]+\.[0-9]+((a|b|rc)[0-9]+(\.dev[0-9]+)?|\.dev[0-9]+)$') {
                $branchIdentity = '.+'
            }
            $identity = '^https://github\.com/MinorGlitch/ethernity/\.github/workflows/pyinstaller\.yml@refs/(tags/' + [regex]::Escape($tag) + '|heads/' + $branchIdentity + ')$'
            & $cosign.Source verify-blob --bundle $bundle --certificate-identity-regexp $identity --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' $zipPath
            if ($LASTEXITCODE -ne 0) { throw 'Sigstore verification failed.' }
        }
        $extract = Join-Path $stage 'extract'
        Expand-Release $zipPath $extract $stem
        $candidate = Join-Path $extract $stem
        $exe = Join-Path $candidate 'ethernity.exe'
        if (-not (Test-Path -LiteralPath $exe)) { throw 'Archive has no executable.' }
        $actual = & $exe --version
        if ($LASTEXITCODE -ne 0 -or "$actual".Trim() -ne "ethernity $Version") {
            throw "Replacement cannot run or has the wrong version: $actual. Existing installation was kept."
        }
        Set-Content -LiteralPath (Join-Path $candidate '.installed-version') -Value $tag -Encoding ascii
        $previous = Join-Path $stage 'previous'
        if (Test-Path -LiteralPath $Current) { Move-Item -LiteralPath $Current -Destination $previous }
        Move-Item -LiteralPath $candidate -Destination $Current
        $replaced = $true
        Set-CommandPath $false
        Set-Content -LiteralPath $Marker -Value 'ethernity-installer-v1' -Encoding ascii
        $committed = $true
        if (Test-Path -LiteralPath $LegacyVersion) { Remove-Item -LiteralPath $LegacyVersion -Force }
        Write-Host "Installed Ethernity $Version. Open a new terminal and run: ethernity"
    }
}
finally {
    if (-not $committed) {
        if ($replaced) { Remove-Item -LiteralPath $Current -Recurse -Force }
        if ($previous -and (Test-Path -LiteralPath $previous)) { Move-Item -LiteralPath $previous -Destination $Current }
        [Environment]::SetEnvironmentVariable('Path', $originalPath, 'User')
    }
    if ($stage -and (Test-Path -LiteralPath $stage)) { Remove-Item -LiteralPath $stage -Recurse -Force }
    $lock.Dispose()
    Remove-Item -LiteralPath $lockPath -Force
    if ($Uninstall -and $committed -and -not (Get-ChildItem -LiteralPath $InstallRoot -Force)) {
        Remove-Item -LiteralPath $InstallRoot
    }
}
