# Install Ethernity

Ethernity opens in your terminal by default. Packaged downloads include Python, the PDF fonts,
browser mode, and the browser recovery kits. You do not need to install Python for those downloads.

## Browser mode

Run `ethernity --web` to open the same app in your default browser. The app runs on your computer,
uses your usual settings, and reads and writes your local files. Fonts and scripts are local too;
an internet connection is not needed. No additional installation is required.

Keep the launching terminal open. Ctrl+C stops the server and its open sessions. Closing or
refreshing a browser tab ends that tab's app session; reopening starts a new one. Files already
written remain on disk.

The server listens only on `127.0.0.1`, chooses an available port, and prints a private link for
that launch. Use `ethernity --web --no-open` to open that link yourself. It cannot be used from
another computer. The file picker and Open folder actions operate on the computer running Ethernity.

Browser mode is separate from the standalone HTML recovery kit, which needs no running Ethernity
process and can be kept with a backup.

## Choose a release

This checkout describes Ethernity 1.2, including the new installers. Until 1.2 is published,
use the archives on [GitHub Releases](https://github.com/MinorGlitch/ethernity/releases/latest).
The Homebrew and PyPI channels still contain earlier releases. Follow the README at your
release tag when its commands differ from this guide.

The installer commands below require a release containing `install.sh`, `install.ps1`, and
`SHA256SUMS`. They will be available with 1.2. A script downloaded from a release installs that
release by default. Download a fresh script when upgrading; do not fetch installers from `master`.

## macOS

On Apple silicon, with [Homebrew](https://brew.sh/) installed:

```sh
brew install minorglitch/tap/ethernity
ethernity --version
ethernity
```

Update with `brew update`, then `brew upgrade ethernity`. Remove the application with
`brew uninstall ethernity`. These commands keep your backups and application settings.

Without Homebrew, use the `macos-arm64` [portable download](#portable-downloads) for Apple
silicon. Builds are not notarized. See
[download verification](release_files.md#verification-example) before deciding whether to allow
an unsigned executable through macOS security settings. Do not disable Gatekeeper globally.

Starting with 1.2, we no longer build native Intel Mac archives or Homebrew bottles. Intel Mac
users can use the [Python installation route](#python-users); Intel macOS is not tested in CI.

## Windows

Use 64-bit Windows. The native archive is x64; there is no native Windows ARM build.

Download `install.ps1` from the release you want, open PowerShell in the download directory,
and run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

Open a new terminal, then run:

```powershell
ethernity --version
ethernity
```

The installer puts the complete application in `%LOCALAPPDATA%\Programs\Ethernity\current`
and adds that directory to your user PATH. It does not require administrator access. To update,
download the new release's installer and run the same command. A failed download, checksum,
or executable check leaves the working installation in place.

To remove an installation made by this script:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Uninstall
```

Removal also removes its PATH entry. Your settings and backups stay where they are.
If you used `-InstallRoot` when installing, pass the same path when updating or removing it.
The installer can upgrade installations made by the earlier Ethernity PowerShell script.

WinGet support is being prepared. The release will include a manifest for the same Windows ZIP,
but `winget install` will not work until the package is accepted into the WinGet community
repository. Keep using the installer or ZIP until then. After acceptance, install, upgrade,
and remove it through WinGet rather than mixing installation methods.

## Linux

The installer supports x86_64 and ARM64 with glibc 2.35 or newer. Ubuntu 22.04 is the tested
minimum. Alpine and other musl-based distributions cannot use these native archives. Other
Linux distributions may need additional system libraries; the executable check stops an install
that cannot run.

Download `install.sh` from the release you want and run:

```sh
sh install.sh
ethernity --version
ethernity
```

The installer needs `curl`, `tar`, and the usual system tools, including `sha256sum`.
It installs under `${XDG_DATA_HOME:-$HOME/.local/share}/ethernity/app` and adds a command link
at `~/.local/bin/ethernity`. No root access is needed. If `~/.local/bin` is not on your PATH,
add this line to your shell startup file, then open a new terminal:

```sh
export PATH="$HOME/.local/bin:$PATH"
```

To update, download the new release's installer and run it again. To remove this installation:

```sh
sh install.sh --uninstall
```

The installer leaves settings and backups alone. Custom `--install-root` and `--bin-dir`
paths must also be supplied when updating or removing that installation.

If you already use Homebrew on Linux, `brew install minorglitch/tap/ethernity` remains available.
Use Homebrew's upgrade and uninstall commands for that installation.

## Portable downloads

Use an archive when you do not want an installer or need to move the application to an offline
computer. Download the file matching the operating system and processor of the computer that
will run it. Windows uses `.zip`; Linux and macOS use `.tar.gz`.

1. Download the archive and its `.sigstore.json` file from the same release.
2. [Verify the download](release_files.md#verification-example) before transferring it.
3. Extract the whole archive into a new directory. Keep the executable with all accompanying files.
4. Open a terminal in that directory and run `./ethernity` on macOS/Linux or `.\ethernity.exe`
   in PowerShell.

To update a portable copy, extract the new version into a separate directory and try it before
removing the old directory. To uninstall, delete only the extracted application directory.
Store backups outside that directory. Portable copies do not add a command to PATH.

The 1.2 installers also accept local downloads. For example, on Linux:

```sh
sh install.sh --version 1.2.0 \
  --archive ./ethernity-v1.2.0-linux-x64.tar.gz --checksums ./SHA256SUMS
```

The PowerShell equivalents are `-Version`, `-Archive`, and `-Checksums`. Download the script,
archive, and checksum file from the same release, and verify signatures before going offline.

## Download checks

Both direct installers require a matching SHA-256 checksum from the release's `SHA256SUMS`.
A missing or mismatched checksum stops installation. The checksum detects changed or damaged
downloads; a checksum downloaded alongside an archive is not independent proof of its publisher.

For publisher verification, install [cosign](https://docs.sigstore.dev/cosign/system_config/installation/)
and pass `--verify-signature` on Linux or `-VerifySignature` on Windows. This checks the archive's
Sigstore bundle against Ethernity's release workflow and GitHub's identity provider. Missing
cosign or a failed signature stops installation. There is no automatic verification bypass.
This option downloads the bundle and requires an internet connection.

## Python users

With [uv](https://docs.astral.sh/uv/getting-started/installation/) installed:

```sh
uv tool install --python 3.13 ethernity-paper
ethernity
```

uv installs a suitable Python if needed and isolates Ethernity's dependencies. If the command is
not found, run `uv tool update-shell` and open a new terminal. Update with
`uv tool upgrade ethernity-paper`; uninstall with `uv tool uninstall ethernity-paper`.

If you already have Python 3.11 or newer and [pipx](https://pipx.pypa.io/stable/installation/):

```sh
pipx install ethernity-paper
```

Use `pipx upgrade ethernity-paper` to update and `pipx uninstall ethernity-paper` to remove it.
The package name is `ethernity-paper`; the installed command is `ethernity`.

## After installing or upgrading

Run `ethernity --version` to check which copy your terminal finds. If it is the wrong one,
use `command -v ethernity` on macOS/Linux or `Get-Command ethernity -All` in PowerShell. Remove
the old installation using the method that installed it.

Start `ethernity`, create a backup of a disposable file, and test restoring it. After an upgrade,
also restore an existing backup into a new destination. Updating the application does not require
reprinting a compatible backup.
