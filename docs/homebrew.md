# Homebrew Packaging

This project can be distributed via Homebrew on both macOS and Linux.

## Current Path (Tap, Cross-Platform)

Use the source formula template at:

- `scripts/homebrew_ethernity_core.rb`

It is wired for:

- macOS x64
- macOS arm64
- Linux x64
- Linux arm64

Automatic tap updates are wired in:

- `.github/workflows/homebrew-tap.yml`

Publish flow:

1. Create/update a tap repo (default: `MinorGlitch/homebrew-ethernity`).
2. Place the formula at `Formula/ethernity.rb` in the tap repo.
3. Commit and push the tap repo.

User install flow:

```bash
brew tap MinorGlitch/ethernity
brew install ethernity
```

Note: Homebrew tap shorthand `MinorGlitch/ethernity` maps to GitHub repo
`MinorGlitch/homebrew-ethernity`.

If the tap is already added and no other formula with the same name conflicts, plain
`brew install ethernity` works.

### Automation setup

The workflow updates the tap formula whenever a non-draft, non-prerelease GitHub release is published.
It resolves the release tag and writes a source-based `Formula/ethernity.rb` pinned to that tag tarball.

Required repository secret:

- `HOMEBREW_TAP_TOKEN`: a token with push access to your tap repository.

Optional repository variable:

- `HOMEBREW_TAP_REPO`: tap slug (defaults to `MinorGlitch/homebrew-ethernity`).

Manual backfill:

```bash
# Run "Update Homebrew Tap" workflow_dispatch with:
# - release_tag=v0.2.1 to target a specific tag
# - release_tag omitted to use latest stable release tag
```

## Homebrew Core Path (`brew install ethernity` without tap)

To land in Homebrew core, maintain a source-build formula in
`homebrew-core/Formula/e/ethernity.rb` and open a PR to Homebrew/homebrew-core.

Core expectations:

- Build from source (not release binaries).
- Pass `brew audit --new --strict --online ethernity`.
- Pass `brew test ethernity` on macOS and Linux CI.
- Keep dependency/resource blocks reproducible and pinned.

Given Ethernity's Python + Playwright stack, the tap formula above is the fastest reliable
cross-platform route today. Core is still possible, but needs a dedicated source-formula pass.

## Local Core Candidate

A local source-build candidate formula is available at:

- `scripts/homebrew_ethernity_core.rb`

Try it locally:

```bash
brew tap-new <you>/local-ethernity-test --no-git
cp scripts/homebrew_ethernity_core.rb "$(brew --repo <you>/local-ethernity-test)/Formula/ethernity.rb"
brew install --build-from-source <you>/local-ethernity-test/ethernity
brew test ethernity
brew untap <you>/local-ethernity-test
```
