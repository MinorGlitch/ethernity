# Release Artifacts and Verification

This document defines the release packaging outputs published via GitHub Releases.

## Naming Scheme

All binary archives use:

```text
ethernity-{tag}-{os}-{arch}-pyinstaller-onedir.{zip|tar.gz}
```

Examples:

- `ethernity-vX.Y.Z-linux-x64-pyinstaller-onedir.tar.gz`
- `ethernity-vX.Y.Z-windows-x64-pyinstaller-onedir.zip`

## Published Variant Matrix

Current release matrix:

- Linux x64 (`tar.gz`)
- Linux arm64 (`tar.gz`)
- macOS x64 (`tar.gz`)
- macOS arm64 (`tar.gz`)
- Windows x64 (`zip`)

## Companion Files

Each archive is published with sidecars:

- `*.sha256` - SHA-256 checksum
- `*.sbom.cdx.json` - CycloneDX SBOM
- `*.sigstore.json` - Sigstore bundle (required provenance artifact)
- `*.sig` and `*.pem` - optional detached signature/certificate pair (may be absent)

Notes:

- Bundle-first verification is the canonical path.
- If detached files are present, both `.sig` and `.pem` are expected together.

## Verification Workflow

### 1) Verify checksum

Linux/macOS:

```sh
sha256sum -c ethernity-vX.Y.Z-linux-x64-pyinstaller-onedir.tar.gz.sha256
```

macOS with `shasum` fallback:

```sh
shasum -a 256 -c ethernity-vX.Y.Z-macos-arm64-pyinstaller-onedir.tar.gz.sha256
```

### 2) Verify Sigstore bundle (recommended)

```sh
cosign verify-blob \
  --bundle ethernity-vX.Y.Z-linux-x64-pyinstaller-onedir.tar.gz.sigstore.json \
  ethernity-vX.Y.Z-linux-x64-pyinstaller-onedir.tar.gz
```

Optional stricter identity constraints:

```sh
cosign verify-blob \
  --bundle ethernity-vX.Y.Z-linux-x64-pyinstaller-onedir.tar.gz.sigstore.json \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity-regexp 'https://github.com/.+/.+/.github/workflows/pyinstaller.yml@refs/tags/.+' \
  ethernity-vX.Y.Z-linux-x64-pyinstaller-onedir.tar.gz
```

### 3) Verify detached signature (optional path)

Use this only when both `.sig` and `.pem` exist:

```sh
cosign verify-blob \
  --certificate ethernity-vX.Y.Z-linux-x64-pyinstaller-onedir.tar.gz.pem \
  --signature ethernity-vX.Y.Z-linux-x64-pyinstaller-onedir.tar.gz.sig \
  ethernity-vX.Y.Z-linux-x64-pyinstaller-onedir.tar.gz
```

### 4) Inspect SBOM

```sh
cat ethernity-vX.Y.Z-linux-x64-pyinstaller-onedir.sbom.cdx.json
```

## Release Integrity Expectations

A complete archive set for each variant includes:

- archive
- checksum
- SBOM
- bundle files for archive/checksum/SBOM

Release publishing is fail-closed: missing required variant artifacts should block publication.

## Troubleshooting

### Missing `.sig`/`.pem`

This can be valid when bundle-first signing is used. Check for `.sigstore.json` files.

### Checksum mismatch

Do not use the artifact. Re-download and verify again.

### Verification fails with identity constraints

Confirm you are verifying the correct tag artifact and workflow identity pattern.

### Wrong architecture artifact

Select the archive matching your target OS and CPU architecture from the variant matrix.
