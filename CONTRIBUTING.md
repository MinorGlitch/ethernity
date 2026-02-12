# Contributing to Ethernity

Thanks for contributing.

This project is still experimental, so small, focused changes with clear tests and docs are preferred.

## Development Setup

### Prerequisites

- Python 3.13+
- `uv`
- Node.js 20+ (for recovery kit build)

### Initial Setup

```sh
git clone https://github.com/MinorGlitch/ethernity.git
cd ethernity
uv sync --extra dev --extra build
uv run playwright install chromium
```

## Daily Workflow

1. Create a branch from `master`.
2. Make one focused change set.
3. Add or update tests.
4. Update docs if behavior/UX/output changed.
5. Run quality gates locally.
6. Open a PR with clear scope and rationale.

## Quality Gates

Run before opening a PR:

```sh
uv run pytest tests/unit tests/integration -q
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src
```

Optional, when touching browser kit assets:

```sh
cd kit
npm ci
node build_kit.mjs
cd ..
```

## Pull Request Expectations

- Keep PRs small and reviewable.
- Include tests for logic changes.
- Include docs updates for user-facing behavior changes.
- Avoid mixing unrelated refactors with behavior fixes.
- Use explicit commit messages that explain intent.

## Documentation Expectations

If you change CLI behavior, output contracts, recovery flow, or release artifacts:

- update `README.md` where applicable
- update docs under `docs/` when deeper details are required
- keep command examples aligned with current behavior

## Security-Related Changes

For cryptography, recovery integrity, or authentication-path changes, include:

- explicit threat-model impact summary in PR description
- regression tests for negative/error paths
- compatibility notes for existing artifacts, if relevant

See full disclosure guidance in `SECURITY.md`.

## Automation and Agent Conventions

This repository includes automation-specific conventions in `AGENTS.md`.
If you use coding agents, follow `AGENTS.md` as a required contract.
