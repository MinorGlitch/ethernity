<a id="readme-top"></a>

[![Contributors][contributors-shield]][contributors-url]
[![Forks][forks-shield]][forks-url]
[![Stargazers][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]
[![License][license-shield]][license-url]
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg?style=for-the-badge)](https://www.python.org/downloads/)

<div align="center">
  <img src="images/readme_logo.png" alt="Ethernity logo" width="320">
  <h1 align="center">Ethernity</h1>
  <p align="center">
    Encrypted backups you can recover offline from printed documents.
    <br />
    <a href="https://github.com/MinorGlitch/ethernity/wiki/Getting-Started"><strong>Getting Started</strong></a>
    &middot;
    <a href="https://github.com/MinorGlitch/ethernity/wiki/Backup-Workflow"><strong>Backup Workflow</strong></a>
    &middot;
    <a href="https://github.com/MinorGlitch/ethernity/wiki/Extension-Workflow"><strong>Extension Workflow</strong></a>
    &middot;
    <a href="https://github.com/MinorGlitch/ethernity/wiki/Recovery-Workflow"><strong>Recovery Workflow</strong></a>
    &middot;
    <a href="docs/format.md"><strong>Format Spec</strong></a>
    &middot;
    <a href="SECURITY.md"><strong>Security Policy</strong></a>
  </p>
</div>

## What Ethernity Is

Ethernity is a Python CLI for turning a small file or directory into encrypted recovery artifacts:

- `qr_document.pdf` for scanning
- `recovery_document.pdf` for fallback text recovery
- optional passphrase shard PDFs
- optional signing-key shard PDFs
- an optional browser recovery kit

It is built for situations where you care more about recoverability, custody, and offline handling
than convenience.

This is a good tool for small, high-value data. It is not a replacement for bulk backup systems or
continuous sync tools.

## Main Workflows

- `backup`: create a new standalone root
- `extend`: append changes to an existing unsealed root
- `compact`: flatten a root plus its extensions into a fresh standalone backup
- `recover`: restore the latest validated state or a selected earlier generation
- `mint`: issue new shard PDFs for an existing backup
- `kit`: generate a printable QR document for the browser recovery kit

If your source data changes over time, the intended lifecycle is:

1. Create a standalone root with `backup`.
2. Append changes with `extend`.
3. Use `compact` when you want a fresh standalone root again.

That lifecycle is not an advanced edge case. It is the normal way to use Ethernity when the source
data changes over time.

## Primary Lifecycle

Think of the primary feature set like this:

| Job | Command | Result |
| --- | --- | --- |
| Create an initial backup set | `backup` | a standalone root |
| Record later changes | `extend` | a new generation under `extensions/` |
| Re-root the latest state | `compact` | a fresh standalone backup |
| Restore data | `recover` | latest validated state by default, or a selected earlier state |

If you only present `backup` and `recover` to users, they will assume the product is snapshot-only.
It is not. The current product model is root-plus-extensions with explicit compaction.

## When To Use It

Ethernity is a good fit when you want:

- offline-capable recovery
- printable artifacts that can live in separate custody paths
- threshold-based recovery instead of one person holding everything
- a documented format and explicit operator workflows

It is a poor fit when you want:

- continuous background backup
- large archival datasets
- hands-off sync between machines
- a system that works well without recovery drills

## Quick Start

### macOS and Linux

Homebrew is the shortest path:

```sh
brew tap minorglitch/tap
brew install ethernity
ethernity --help
```

If you prefer Python-managed installs:

```sh
pipx install ethernity-paper
ethernity --help
```

### Windows

Use the PowerShell installer:

```powershell
$ProgressPreference = 'SilentlyContinue'
Invoke-WebRequest "https://raw.githubusercontent.com/MinorGlitch/ethernity/master/install.ps1" -OutFile install.ps1
powershell -ExecutionPolicy Bypass -File .\install.ps1
ethernity --help
```

For manual archive verification, use [Wiki: Release Artifacts](https://github.com/MinorGlitch/ethernity/wiki/Release-Artifacts).

### Install From Source

```sh
git clone https://github.com/MinorGlitch/ethernity.git
cd ethernity
uv sync --extra dev --extra build
uv run ethernity --help
```

## First Drill

Run this once with test data before you trust the workflow with anything important.

```sh
printf "ethernity test payload\n" > payload.txt

ethernity backup \
  --input ./payload.txt \
  --output-dir ./backup-demo \
  --passphrase "ethernity test passphrase"

ethernity recover \
  --scan ./backup-demo \
  --passphrase "ethernity test passphrase" \
  --output ./restored.txt

cmp ./payload.txt ./restored.txt
```

If `cmp` prints nothing and exits successfully, the drill passed.

On Windows PowerShell:

```powershell
fc.exe /b .\payload.txt .\restored.txt
```

## Working With Changes

When the source data changes, do not rewrite the old backup set by hand.

Create an initial root:

```sh
ethernity backup \
  --input-dir ./docs \
  --output-dir ./backup-root \
  --passphrase "example passphrase"
```

Append changes to that root:

```sh
ethernity extend \
  --root-dir ./backup-root \
  --input-dir ./docs \
  --base-dir ./docs \
  --passphrase "example passphrase"
```

Recover the latest logical state:

```sh
ethernity recover \
  --scan ./backup-root \
  --passphrase "example passphrase" \
  --output ./restored-docs
```

Flatten the chain into a fresh standalone backup:

```sh
ethernity compact \
  --root-dir ./backup-root \
  --output-dir ./backup-compacted \
  --passphrase "example passphrase"
```

Notes:

- `extend` only works on unsealed roots
- recovery defaults to the latest validated state
- `compact` gives you a new standalone root without modifying the old one in place

For the operator model behind that flow, use [Wiki: Extension Workflow](https://github.com/MinorGlitch/ethernity/wiki/Extension-Workflow).

## Document Preview

Sentinel preview pages from the generated PDF set:

<p align="center">
  <img src="images/readme/sentinel_main_preview.png" alt="Sentinel main document preview" width="24%">
  <img src="images/readme/sentinel_shard_preview.png" alt="Sentinel shard document preview" width="24%">
  <img src="images/readme/sentinel_kit_preview.png" alt="Sentinel recovery kit preview" width="24%">
  <img src="images/readme/sentinel_fallback_preview.png" alt="Sentinel fallback document preview" width="24%">
</p>

For the other supported designs, use [Wiki: Template Gallery](https://github.com/MinorGlitch/ethernity/wiki/Template-Gallery).

## Safety Rules

- Start with test data, not production secrets.
- Keep main docs, fallback docs, and shards in separate custody paths.
- Keep one independent backup path outside Ethernity.
- Run a real recovery drill before you trust any procedure.
- Prefer offline recovery environments when practical.

Ethernity can give you a recoverable artifact set. It cannot compensate for weak passphrases,
sloppy custody, or untested procedures.

## Documentation Map

Use the wiki for operator guidance:

- [Getting Started](https://github.com/MinorGlitch/ethernity/wiki/Getting-Started)
- [Backup Workflow](https://github.com/MinorGlitch/ethernity/wiki/Backup-Workflow)
- [Extension Workflow](https://github.com/MinorGlitch/ethernity/wiki/Extension-Workflow)
- [Backup Playbooks](https://github.com/MinorGlitch/ethernity/wiki/Backup-Playbooks)
- [Recovery Workflow](https://github.com/MinorGlitch/ethernity/wiki/Recovery-Workflow)
- [Recovery Kit](https://github.com/MinorGlitch/ethernity/wiki/Recovery-Kit)
- [Troubleshooting](https://github.com/MinorGlitch/ethernity/wiki/Troubleshooting)
- [Command Cheatsheet](https://github.com/MinorGlitch/ethernity/wiki/Command-Cheatsheet)
- [Release Artifacts](https://github.com/MinorGlitch/ethernity/wiki/Release-Artifacts)

Use the in-repo docs for contracts and reference material:

- [docs/format.md](docs/format.md): normative format specification
- [docs/format_notes.md](docs/format_notes.md): rationale and operational notes
- [docs/format_changes.md](docs/format_changes.md): compatibility change log
- [docs/cli_api.md](docs/cli_api.md): NDJSON API contract for GUI and automation clients
- [docs/release_artifacts.md](docs/release_artifacts.md): in-repo release verification anchor

## Development Quickstart

```sh
git clone https://github.com/MinorGlitch/ethernity.git
cd ethernity
uv sync --extra dev --extra build
uv run playwright install chromium
```

Core checks:

```sh
uv run pre-commit run --all-files
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src
uv run pyright
uv run check-jsonschema --check-metaschema docs/cli_api.schema.json
uv run typos .
uv run pytest tests/unit tests/integration -q
cd kit
npm ci
npm run lint
npm run format:check
npm test
node build_kit.mjs
cd ..
```

Use [CONTRIBUTING.md](CONTRIBUTING.md) for contribution workflow and quality gates.

## Contributing

Focused pull requests with tests and docs updates are preferred.

Before opening a PR, read:

- [CONTRIBUTING.md](CONTRIBUTING.md)
- [SECURITY.md](SECURITY.md)
- [AGENTS.md](AGENTS.md)

## Credits

Ethernity was heavily inspired by [Paperback](https://github.com/cyphar/paperback) by cyphar.

It also builds on work from:

- [Rememory](https://github.com/eljojo/rememory)
- [age](https://github.com/FiloSottile/age) via [pyrage](https://github.com/str4d/rage)
- [PyCryptodome](https://github.com/Legrandin/pycryptodome)
- [Typer](https://github.com/fastapi/typer)
- [Rich](https://github.com/Textualize/rich)
- [Questionary](https://github.com/tmbo/questionary)
- [Playwright](https://playwright.dev/python/)

## License

GPLv3 or later. See [LICENSE](LICENSE).

<p align="right">(<a href="#readme-top">back to top</a>)</p>

[contributors-shield]: https://img.shields.io/github/contributors/MinorGlitch/ethernity.svg?style=for-the-badge
[contributors-url]: https://github.com/MinorGlitch/ethernity/graphs/contributors
[forks-shield]: https://img.shields.io/github/forks/MinorGlitch/ethernity.svg?style=for-the-badge
[forks-url]: https://github.com/MinorGlitch/ethernity/network/members
[stars-shield]: https://img.shields.io/github/stars/MinorGlitch/ethernity.svg?style=for-the-badge
[stars-url]: https://github.com/MinorGlitch/ethernity/stargazers
[issues-shield]: https://img.shields.io/github/issues/MinorGlitch/ethernity.svg?style=for-the-badge
[issues-url]: https://github.com/MinorGlitch/ethernity/issues
[license-shield]: https://img.shields.io/github/license/MinorGlitch/ethernity.svg?style=for-the-badge
[license-url]: https://github.com/MinorGlitch/ethernity/blob/master/LICENSE
