#!/bin/sh
# Copyright (C) 2026 Alex Stoyanov. GPL-3.0-or-later.
# Install the published Linux archive without Python or administrator access.
set -eu

version=''
root="${XDG_DATA_HOME:-$HOME/.local/share}/ethernity/app"
bin_dir="$HOME/.local/bin"
archive=''
checksums=''
verify_signature=false
uninstall=false
repo='https://github.com/MinorGlitch/ethernity'

fail() { printf '%s\n' "Error: $*" >&2; exit 1; }
usage() {
    cat <<'HELP'
Usage: sh install.sh [--version VERSION] [--install-root PATH] [--bin-dir PATH]
                     [--archive FILE --checksums FILE] [--verify-signature]
       sh install.sh --uninstall [--install-root PATH] [--bin-dir PATH]

Installs for the current user. Downloads are checked against the release's
SHA256SUMS. --verify-signature also requires cosign and checks release provenance.
For offline installation supply an archive, SHA256SUMS, and --version.
Uninstall removes only this installation and its command link, keeping app data.
HELP
}
while [ "$#" -gt 0 ]; do
    case "$1" in
        --version|--install-root|--bin-dir|--archive|--checksums)
            [ "$#" -ge 2 ] && [ -n "$2" ] || fail "Missing value for $1"
            case "$1" in
                --version) version="$2" ;;
                --install-root) root="$2" ;;
                --bin-dir) bin_dir="$2" ;;
                --archive) archive="$2" ;;
                --checksums) checksums="$2" ;;
            esac
            shift 2 ;;
        --verify-signature) verify_signature=true; shift ;;
        --uninstall) uninstall=true; shift ;;
        --help|-h) usage; exit 0 ;;
        *) fail "Unknown option: $1" ;;
    esac
done

case "$root:$bin_dir" in *'
'*) fail 'Paths must not contain newlines' ;; esac
case "$root" in /*) ;; *) fail '--install-root must be absolute' ;; esac
case "$bin_dir" in /*) ;; *) fail '--bin-dir must be absolute' ;; esac
[ "$root" != / ] && [ "$root" != "$HOME" ] || fail 'Choose a dedicated install directory'
[ ! -L "$root" ] || fail 'Install root must not be a symbolic link'
if [ -e "$root" ]; then
    [ -f "$root/.ethernity-install" ] || fail "Not an Ethernity installation: $root"
    [ "$(cat "$root/.ethernity-install")" = 'ethernity-installer-v1' ] || fail 'Unknown installation marker'
fi
command_path="$bin_dir/ethernity"
owns_link() { [ -L "$command_path" ] && [ "$(readlink "$command_path")" = "$root/current/ethernity" ]; }
if [ -e "$command_path" ] || [ -L "$command_path" ]; then
    owns_link || fail "Another installation owns $command_path"
fi

if "$uninstall"; then
    [ -d "$root" ] || { printf '%s\n' 'Ethernity is not installed here.'; exit 0; }
else
    mkdir -p "$root" "$bin_dir"
    printf '%s\n' 'ethernity-installer-v1' > "$root/.ethernity-install"
fi
mkdir "$root/.install-lock" 2>/dev/null || fail "Another installer is running. If it was interrupted, remove $root/.install-lock and retry."
stage=''
committed=false
replacement=false
cleanup() {
    if ! "$committed" && [ -n "$stage" ]; then
        if "$replacement"; then rm -rf "$root/current"; fi
        if [ -d "$stage/previous" ]; then mv "$stage/previous" "$root/current"; fi
    fi
    [ -z "$stage" ] || rm -rf "$stage"
    rmdir "$root/.install-lock" 2>/dev/null || :
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if "$uninstall"; then
    owns_link && rm "$command_path"
    rm -rf "$root/current"
    rm -f "$root/.ethernity-install"
    cleanup
    rmdir "$root" 2>/dev/null || :
    printf '%s\n' 'Ethernity uninstalled. Settings and backups were kept.'
    exit 0
fi

[ "$(uname -s)" = Linux ] || fail 'This installer is for Linux. Use Homebrew or the macOS archive on macOS.'
case "$(uname -m)" in
    x86_64|amd64) arch=x64 ;;
    aarch64|arm64) arch=arm64 ;;
    *) fail 'Supported Linux architectures are x86_64 and arm64' ;;
esac
glibc=$(getconf GNU_LIBC_VERSION 2>/dev/null) || fail 'This build requires glibc 2.35 or newer; musl/Alpine is not supported'
glibc=${glibc#glibc }
awk -v v="$glibc" 'BEGIN { split(v,a,"."); exit !(a[1]>2 || (a[1]==2 && a[2]>=35)) }' || fail 'This build requires glibc 2.35 or newer'
download() { curl --fail --location --silent --show-error --proto '=https' --proto-redir '=https' "$1" -o "$2"; }
if [ -z "$version" ]; then
    [ -z "$archive$checksums" ] || fail 'Offline installation requires --version'
    url=$(curl --fail --location --silent --show-error --proto '=https' --proto-redir '=https' -o /dev/null -w '%{url_effective}' "$repo/releases/latest")
    version=${url##*/}
fi
version=${version#v}
printf '%s\n' "$version" | grep -Eq '^[0-9][0-9A-Za-z._-]*$' || fail 'Use a release version such as 1.2.0'
tag="v$version"
name="ethernity-$tag-linux-$arch.tar.gz"
stage=$(mktemp -d "$root/.stage.XXXXXXXX")
if [ -n "$archive$checksums" ]; then
    [ -f "$archive" ] && [ -f "$checksums" ] || fail 'Supply both --archive and --checksums'
    "$verify_signature" && fail 'Verify the Sigstore bundle before offline installation; --verify-signature requires online downloads'
    cp "$archive" "$stage/$name"
    cp "$checksums" "$stage/SHA256SUMS"
else
    download "$repo/releases/download/$tag/$name" "$stage/$name"
    download "$repo/releases/download/$tag/SHA256SUMS" "$stage/SHA256SUMS"
fi
expected=$(awk -v name="$name" '$2==name { print $1; count++ } END { if(count!=1) exit 1 }' "$stage/SHA256SUMS") || fail 'Archive is missing or duplicated in SHA256SUMS'
printf '%s\n' "$expected" | grep -Eq '^[a-fA-F0-9]{64}$' || fail 'Invalid SHA-256 checksum'
printf '%s  %s\n' "$expected" "$name" > "$stage/checksum"
(cd "$stage" && sha256sum --check checksum) || fail 'Archive checksum does not match'
if "$verify_signature"; then
    command -v cosign >/dev/null || fail 'Install cosign to use --verify-signature'
    download "$repo/releases/download/$tag/$name.sigstore.json" "$stage/bundle.json"
    escaped_version=$(printf '%s' "$version" | sed 's/\./\\./g')
    branch_identity=master
    if printf '%s\n' "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+((a|b|rc)[0-9]+(\.dev[0-9]+)?|\.dev[0-9]+)$'; then
        branch_identity='.+'
    fi
    identity="^$repo/\\.github/workflows/pyinstaller\\.yml@refs/(tags/v$escaped_version|heads/$branch_identity)$"
    cosign verify-blob --bundle "$stage/bundle.json" --certificate-identity-regexp "$identity" \
        --certificate-oidc-issuer https://token.actions.githubusercontent.com "$stage/$name"
fi
# Reject paths outside the release directory. PyInstaller includes library symlinks;
# permit only relative links without parent traversal, and reject special files.
archive_root="ethernity-$tag-linux-$arch"
tar -tzf "$stage/$name" > "$stage/members"
awk -v root="$archive_root" '$0!=root && index($0,root"/")!=1 { exit 1 } /(^|\/)\.\.(\/|$)/ { exit 1 }' "$stage/members" || fail 'Unsafe archive paths'
tar -tvzf "$stage/$name" | awk '
    substr($0,1,1)=="l" {
        split($0,parts," -> "); link=parts[2]
        if(link=="" || link ~ /^\// || link ~ /(^|\/)\.\.(\/|$)/) exit 1
        next
    }
    substr($0,1,1)!="-" && substr($0,1,1)!="d" { exit 1 }
' || fail 'Archive contains unsafe links or special files'
mkdir "$stage/extract"
tar -xzf "$stage/$name" --no-same-owner -C "$stage/extract"
candidate="$stage/extract/$archive_root"
[ -x "$candidate/ethernity" ] || fail 'Archive has no executable'
actual=$("$candidate/ethernity" --version) || fail 'Replacement cannot run; existing installation was kept'
[ "$actual" = "ethernity $version" ] || fail "Unexpected executable version: $actual"
printf '%s\n' "$tag" > "$candidate/.installed-version"
# Both renames stay on the installation filesystem. Restore the old copy on failure.
[ ! -L "$root/current" ] || fail 'Installed directory must not be a symbolic link'
if [ -d "$root/current" ]; then mv "$root/current" "$stage/previous"; fi
if ! mv "$candidate" "$root/current"; then
    fail 'Could not install replacement; restoring previous installation'
fi
replacement=true
if ! ln -sf "$root/current/ethernity" "$command_path"; then
    fail 'Could not create command link; restoring previous installation'
fi
committed=true
printf 'Installed Ethernity %s. Run: %s\n' "$version" "$command_path"
case ":$PATH:" in *":$bin_dir:"*) ;; *) printf 'Add this directory to PATH: %s\n' "$bin_dir" ;; esac
