<a id="readme-top"></a>

[![Contributors][contributors-shield]][contributors-url]
[![Forks][forks-shield]][forks-url]
[![Stargazers][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]
[![License][license-shield]][license-url]
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg?style=for-the-badge)](https://www.python.org/downloads/)

<div align="center">
  <img src="images/banner.png" alt="Ethernity banner" width="100%">
  <h1 align="center">Ethernity</h1>
  <p align="center">
    Secure, offline-recoverable backups with printable QR documents and a browser recovery kit.
    <br />
    <a href="docs/format.md"><strong>Format spec</strong></a>
    <br />
    <a href="https://github.com/MinorGlitch/ethernity/issues">Issues</a>
    &middot;
    <a href="https://github.com/MinorGlitch/ethernity/issues/new?labels=bug">Report Bug</a>
    &middot;
    <a href="https://github.com/MinorGlitch/ethernity/issues/new?labels=enhancement">Request Feature</a>
  </p>
</div>

## Status (Experimental)

Ethernity is still experimental and under active development. The document format and CLI may
change without notice, and backward compatibility is not guaranteed yet. Do not treat this as a
stable backup system—always test recovery and keep independent backups.

## About The Project

Ethernity is a Python CLI that turns important files into printable recovery documents. It
creates QR codes plus human-readable fallback text so you can store backups offline and still
recover them later without special tools. A companion browser recovery kit runs locally to help
scan and reconstruct the data when you need it.

This is for people who want durable, offline backups without relying on cloud accounts or
vendor formats.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Features

### Encryption & Security
- **age encryption** - Modern, well-reviewed encryption using the [age](https://age-encryption.org) format
- **BIP-39 passphrases** - Human-readable 12-24 word mnemonic phrases (same standard used by crypto wallets)
- **Shamir secret sharing** - Split your passphrase across multiple documents with configurable thresholds (e.g., 2-of-3)
- **Ed25519 signatures** - Cryptographic verification that documents haven't been tampered with

### Document Generation
- **QR codes** - High-density data encoding, scannable with any phone camera
- **Fallback text** - z-base-32 encoded blocks for manual entry if QR scanning fails
- **Multiple templates** - Choose from different visual designs (`ledger`, `archive_dossier`, `maritime_ledger`, `midnight_archive`)
- **Paper sizes** - A4 and US Letter support

### Recovery Options
- **Browser recovery kit** - Standalone HTML file that works offline in any modern browser
- **CLI recovery** - Reconstruct files directly from the command line
- **Partial recovery** - Paste fallback text in chunks if scanning is imperfect
- **Shard reconstruction** - Combine threshold shares to recover the passphrase

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Use Cases

Ethernity is built for durable, offline backups of sensitive data:

- **Password manager exports** - Back up your vault with a recovery path that doesn't depend on the vendor
- **Crypto wallet seeds** - Store seed phrases or key files with threshold splitting for security
- **Personal documents** - Encrypted archives of important records
- **Disaster recovery** - "Fire drill" backups stored in a safe, safety deposit box, or with trusted contacts
- **Digital estate planning** - Ensure heirs can access critical data

<p align="right">(<a href="#readme-top">back to top</a>)</p>

### Built With

| Category | Libraries |
|----------|-----------|
| CLI & UI | [Typer](https://typer.tiangolo.com/), [Rich](https://rich.readthedocs.io/), [Questionary](https://questionary.readthedocs.io/) |
| Encryption | [pyrage](https://github.com/woodruffw/pyrage) (age), [PyCryptodome](https://pycryptodome.readthedocs.io/) |
| QR Codes | [Segno](https://segno.readthedocs.io/), [zxing-cpp](https://github.com/zxing-cpp/zxing-cpp) |
| PDF & Images | [fpdf2](https://py-pdf.github.io/fpdf2/), [Pillow](https://pillow.readthedocs.io/), [Playwright](https://playwright.dev/python/) |
| Data Formats | [cbor2](https://cbor2.readthedocs.io/), [mnemonic](https://github.com/trezor/python-mnemonic) (BIP-39) |

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Security Model

Ethernity is designed for protecting sensitive data in offline storage. Here's what it provides and what it doesn't.

### What Ethernity Protects Against

- **Physical theft** - Printed documents are encrypted; the passphrase is required to decrypt
- **Single point of failure** - Shard documents let you split the passphrase so no single document is sufficient
- **Data corruption** - CRC32 checksums detect transmission errors; SHA-256 hashes verify file integrity
- **Vendor lock-in** - Standard formats (age, BIP-39, CBOR) mean you're not dependent on this software existing

### What Ethernity Does NOT Protect Against

- **Compromised generation environment** - If your computer is compromised when you run `ethernity backup`, the attacker may capture the passphrase
- **Weak passphrases** - If you supply your own passphrase instead of generating one, weak passphrases can be brute-forced
- **Physical access to all shards** - If an attacker obtains enough shard documents to meet the threshold, they can reconstruct the passphrase
- **Rubber hose cryptanalysis** - Encryption doesn't help if someone forces you to reveal the passphrase

### Cryptographic Choices

| Component | Algorithm | Notes |
|-----------|-----------|-------|
| Encryption | age (scrypt recipient) | Passphrase-based protection via scrypt KDF (see [age](https://age-encryption.org)) |
| Passphrase | BIP-39 mnemonic | 12-24 words, 128-256 bits of entropy |
| Secret sharing | Shamir secret sharing | Information-theoretic security up to threshold |
| Signatures | Ed25519 | Verifies document authenticity |
| Hashing | SHA-256, BLAKE2b | File integrity and document identification |

### Recommendations

- Generate backups on a trusted, offline machine when possible
- Use generated passphrases (12+ words) rather than custom ones
- Store shard documents in separate physical locations
- Test recovery before relying on backups
- Keep at least one copy of the recovery kit PDF with your documents

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Getting Started

### Prerequisites

- Python 3.13 or later
- Playwright browser binaries (for PDF rendering)

### Installation

**pipx (recommended for CLI tools):**
```sh
pipx install ethernity
playwright install chromium
```

**pip:**
```sh
pip install ethernity
playwright install chromium
```

**From source:**
```sh
git clone https://github.com/MinorGlitch/ethernity.git
cd ethernity
pip install -e .
playwright install chromium
```

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Usage

### Interactive Mode

Run without arguments for a guided wizard:
```sh
ethernity
```

The wizard walks you through selecting files, configuring options, and generating documents.

### Create a Backup

```sh
# Interactive backup wizard
ethernity backup

# Backup specific files
ethernity backup --input secret.txt --input credentials.json

# Generate 3 shard documents requiring 2 to recover
ethernity backup --input vault.kdbx --shard-count 3 --shard-threshold 2

# Use a specific template design
ethernity backup --design midnight_archive --input important.tar.gz

# Specify paper size
ethernity backup --paper Letter --input documents.zip
```

### Configuration

Ethernity uses a single TOML config file. Use `ethernity config` to open it, or `ethernity config --print-path`
to see where it lives.

Common settings:
- `[page].size`: `A4` or `Letter`
- `[qr].chunk_size`: preferred bytes per QR code (lower => more codes, easier scanning)

### Recover Files

```sh
# Interactive recovery wizard
ethernity recover

# Recover by scanning a folder of images/PDFs
ethernity recover --scan ./scans --output recovered.bin
```

The recovery wizard accepts:
- QR code scans (via webcam or uploaded images)
- Pasted fallback text blocks
- A mix of both

### Generate Recovery Kit

The recovery kit is a standalone HTML file that can decrypt and recover your backups without needing Ethernity installed:

```sh
# Generate recovery kit PDF
ethernity kit

# The kit works offline in any modern browser
```

Store a copy of the recovery kit alongside your backup documents.

### Command Reference

```sh
ethernity --help              # Show all commands and global options
ethernity backup --help       # Backup command options
ethernity config --help       # Config command options
ethernity recover --help      # Recovery command options
ethernity kit --help          # Recovery kit options

# Global options
ethernity --version           # Show version
ethernity --paper A4          # Paper size override (A4 or Letter)
ethernity --design ledger     # Set template design
ethernity --config myconf.toml # Use custom config file
```

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Development

### Setup

```sh
# Clone the repository
git clone https://github.com/MinorGlitch/ethernity.git
cd ethernity

# Create virtual environment (Python 3.13+)
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install in development mode with dev dependencies
pip install -e ".[dev]"

# Install Playwright browsers
playwright install chromium
```

### Running Tests

```sh
# Run all tests
pytest

# Run with coverage
pytest --cov=ethernity --cov-report=term-missing

# Run specific test categories
pytest tests/unit/                    # Unit tests only
pytest tests/integration/             # Integration tests
pytest tests/e2e/                     # End-to-end tests

# Run a specific test file
pytest tests/unit/test_qr_codec.py
```

### Code Quality

```sh
# Format and lint with Ruff
ruff check src/ tests/
ruff format src/ tests/

# Type checking with mypy
mypy src/

# Run pre-commit hooks manually
pre-commit run --all-files
```

### Project Structure

```
ethernity/
├── src/ethernity/
│   ├── cli/          # Command-line interface
│   ├── core/         # Core data structures
│   ├── crypto/       # Encryption, signing, secret sharing
│   ├── encoding/     # CBOR, base32, framing
│   ├── formats/      # Envelope and manifest handling
│   ├── qr/           # QR code generation and scanning
│   ├── render/       # PDF and HTML rendering
│   └── templates/    # Document templates (Jinja2)
├── kit/              # Browser recovery kit source
├── tests/            # Test suite
└── docs/             # Documentation
```

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Roadmap

See the [open issues](https://github.com/MinorGlitch/ethernity/issues) for planned work and
known gaps.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Contributing

Contributions are welcome. For significant changes, please open an issue first to discuss the approach.

### Process

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Make your changes
4. Run tests and linting (`pytest && ruff check src/ tests/`)
5. Commit with clear messages
6. Push and open a pull request

### Guidelines

- Follow existing code style (enforced by Ruff)
- Add tests for new functionality
- Update documentation if needed
- Keep commits focused and atomic

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## License

GPLv3 or later. See `LICENSE` for details.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Contact

Project link: https://github.com/MinorGlitch/ethernity

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Acknowledgments

- https://github.com/cyphar/paperback (design inspiration)

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
