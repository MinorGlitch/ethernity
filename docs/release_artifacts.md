# Release Artifacts

This file is the in-repo anchor for release verification. The full operator runbook lives in the
wiki:

- [Wiki: Release Artifacts](https://github.com/MinorGlitch/ethernity/wiki/Release-Artifacts)

## What To Expect In A Release

For each published binary variant, expect:

- the archive itself (`.zip` or `.tar.gz`)
- a CycloneDX SBOM (`*.sbom.cdx.json`)
- a Sigstore bundle for the archive and SBOM (`*.sigstore.json`)

Each release also includes `ethernity-source-vX.Y.Z.tar.gz` plus its SBOM and Sigstore bundle.
That tagged source archive is built after injecting the generated recovery-kit bundles and includes
the frozen extension smoke carriers used by the Homebrew formula. Homebrew must consume this
release asset rather than GitHub's automatically generated tag archive.

Bundle-first verification is the canonical path.

## Extension Compatibility Gates

For releases that include the v1.2 extension profile, CI must pass the frozen extension gates:

- `uv run pytest tests/e2e/test_end_to_end_v1_2_extension_golden.py -v`
- `cd kit && node --test tests/v1_2_extension_frozen_e2e.test.mjs`
- `cd kit && node build_kit.mjs`
- `cd kit && node --test tests/loader_html.test.mjs`
- `cd kit && npm run test:browser`

The canonical `recovery_kit.bundle.html` and `recovery_kit.scanner.bundle.html` artifacts use gzip.
Optional Brotli builds use suffixed `*.brotli.bundle.html` names and never replace the canonical
gzip artifacts. Deterministic gzip builds require the `libdeflate-gzip` executable (provided by the
`libdeflate-tools` package on Ubuntu).

Python wheels and PyInstaller distributions embed only the two canonical gzip bundles. Optional
Brotli files remain standalone build outputs under `kit/dist/`.

The generated canonical bundles must decode to an extension-capable UI and pass the real-Chrome
boot and scrypt Worker smoke before release. Recovery kit bundles are release artifacts, not
committed source files.

## Quick Verification Example

```sh
cosign verify-blob \
  --bundle ethernity-vX.Y.Z-linux-x64.tar.gz.sigstore.json \
  ethernity-vX.Y.Z-linux-x64.tar.gz
```

Use the archive and bundle from the same tag and variant.

## When To Stop

Do not run the binary yet if any of these are true:

- the archive name does not match your OS and CPU
- the `.sigstore.json` file came from a different tag
- Sigstore verification fails

## Related

- [Wiki: Release Artifacts](https://github.com/MinorGlitch/ethernity/wiki/Release-Artifacts)
- [Format spec](format.md)
- [v1.2 extension operations profile](extension_publication_profile.md)
- [Format notes](format_notes.md)
- [Security policy](../SECURITY.md)
