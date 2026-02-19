# Homebrew Packaging

This project can be distributed via Homebrew on both macOS and Linux.

## Current Path (Tap, Cross-Platform)

Use the release-binary formula at:

- `scripts/homebrew_ethernity.rb`

It is wired for:

- macOS x64
- macOS arm64
- Linux x64
- Linux arm64

Automatic tap updates are wired in:

- `.github/workflows/homebrew-tap.yml`

Publish flow:

1. Create/update a tap repo (for example: `MinorGlitch/homebrew-tap`).
2. Place the formula at `Formula/ethernity.rb` in the tap repo.
3. Commit and push the tap repo.

User install flow:

```bash
brew tap MinorGlitch/tap
brew install ethernity
```

If the tap is already added and no other formula with the same name conflicts, plain
`brew install ethernity` works.

### Automation setup

The workflow updates the tap formula whenever a non-draft, non-prerelease GitHub release is published.

Required repository secret:

- `HOMEBREW_TAP_TOKEN`: a token with push access to your tap repository.

Optional repository variable:

- `HOMEBREW_TAP_REPO`: tap slug (defaults to `MinorGlitch/homebrew-tap`).

Manual backfill for an existing tag:

```bash
# Run "Update Homebrew Tap" workflow_dispatch with:
release_tag=v0.2.1
```

## Homebrew Core Path (`brew install ethernity` without tap)

To land in Homebrew core, maintain a source-build formula in
`homebrew-core/Formula/e/ethernity.rb` and open a PR to Homebrew/homebrew-core.

Core expectations:

- Build from source (not release binaries).
- Pass `brew audit --new-formula --strict --online ethernity`.
- Pass `brew test ethernity` on macOS and Linux CI.
- Keep dependency/resource blocks reproducible and pinned.

Given Ethernity's Python + Playwright stack, the tap formula above is the fastest reliable
cross-platform route today. Core is still possible, but needs a dedicated source-formula pass.
