# Release Artifacts

This file is the in-repo anchor for release verification. The full operator runbook lives in the
wiki:

- [Wiki: Release Artifacts](https://github.com/MinorGlitch/ethernity/wiki/Release-Artifacts)

## What To Expect In A Release

For each published binary variant, expect:

- the archive itself (`.zip` or `.tar.gz`)
- a CycloneDX SBOM (`*.sbom.cdx.json`)
- a Sigstore bundle for the archive and SBOM (`*.sigstore.json`)

Bundle-first verification is the canonical path.

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
- [Format notes](format_notes.md)
- [Security policy](../SECURITY.md)
