# Homebrew Packaging

This project can be distributed via Homebrew on both macOS and Linux.

## Current Path (Tap, Cross-Platform)

Use the source formula template at:

- `scripts/homebrew_ethernity_tap.rb`

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

The workflow updates the tap formula when:

- a non-draft, non-prerelease GitHub release is published
- a `v*` git tag is pushed
- `workflow_dispatch` is run manually

It resolves the target tag, loads `uv.lock` from that tag, and writes a source-based
`Formula/ethernity.rb` pinned to that tag tarball.

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

## Local Tap Test

A local source-build tap test template is available at:

- `scripts/homebrew_ethernity_tap.rb`

Try it locally:

```bash
brew tap-new <you>/local-ethernity-test --no-git
cp scripts/homebrew_ethernity_tap.rb "$(brew --repo <you>/local-ethernity-test)/Formula/ethernity.rb"
brew install --build-from-source <you>/local-ethernity-test/ethernity
brew test ethernity
brew untap <you>/local-ethernity-test
```
