# Release Artifacts (Anchor)

This file remains the in-repo anchor for release artifact verification guidance.

Detailed release artifact naming, verification workflows, provenance sidecars, and troubleshooting now
live in the GitHub Wiki:

- [Wiki: Release Artifacts](https://github.com/MinorGlitch/ethernity/wiki/Release-Artifacts)

## Stable Release Verification Baseline

For each published release variant, expect:
- the archive (`.zip` or `.tar.gz`)
- a CycloneDX SBOM (`*.sbom.cdx.json`)
- Sigstore bundle files (`*.sigstore.json`) for archive and SBOM

Bundle-first verification remains the canonical verification path.

## Related In-Repo References

- [Format spec](format.md)
- [Format notes](format_notes.md)
- [Security policy](../SECURITY.md)
