# Ethernity

**Secure, offline-recoverable backups that last forever.**

[![CI](https://github.com/your-org/ethernity/actions/workflows/ci.yml/badge.svg)](https://github.com/your-org/ethernity/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)

Ethernity creates encrypted paper backups of your sensitive files that can be recovered offline using only a web browser. No cloud services, no internet connection required during recovery—just print, store, and recover when needed.

---

## Why Ethernity?

Traditional digital backups fail when you need them most:
- **Cloud services** can shut down, lock your account, or be unavailable
- **USB drives and hard disks** degrade over time and fail without warning
- **Password managers** become inaccessible if you forget the master password

Ethernity solves this by creating **paper backups**:
- **Durable**: Paper stored properly lasts decades (or centuries)
- **Offline recovery**: No internet, no special software—just scan and decrypt in any browser
- **Cryptographically secure**: Industry-standard age encryption with scrypt key derivation
- **Self-contained**: The recovery tool is embedded in the backup itself

---

## How It Works

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Your Files │────▶│  Encrypted  │────▶│  Printable  │
│             │     │   Backup    │     │  QR Codes   │
└─────────────┘     └─────────────┘     └─────────────┘
                           │
                    age encryption
                    with passphrase
```

1. **Backup**: Ethernity encrypts your files with a passphrase and encodes them as QR codes in a printable PDF
2. **Store**: Print the PDF and store it somewhere safe (safe deposit box, fireproof safe, etc.)
3. **Recover**: Scan the QR codes with any device, paste into the recovery tool, enter your passphrase, and download your files

The **recovery kit** is a self-contained HTML file that works completely offline—no servers, no dependencies, just open it in a browser.

---

## Features

- **Strong encryption**: Uses [age](https://age-encryption.org/) with scrypt for passphrase-based encryption
- **QR-based storage**: All data encoded as scannable QR codes
- **Offline recovery**: Browser-based recovery tool with zero external dependencies
- **Secret sharing**: Optionally split your passphrase into shares (e.g., 2-of-3) using Shamir's Secret Sharing
- **Integrity verification**: Cryptographic signatures to detect tampering or corruption
- **Multiple paper sizes**: A4 and US Letter support
- **Cross-platform**: Works on Linux, macOS, and Windows

---

## Installation

### From Source

```bash
# Clone the repository
git clone https://github.com/your-org/ethernity.git
cd ethernity

# Install with pip
pip install .

# Or with pipx (recommended for CLI tools)
pipx install .
```

### Standalone Binary

Download pre-built binaries from the [Releases](https://github.com/your-org/ethernity/releases) page.

---

## Quick Start

### Create a Backup

```bash
# Backup a single file
ethernity backup secret.txt -o backup.pdf

# Backup a directory
ethernity backup ~/documents/important/ -o backup.pdf

# Backup with secret sharing (2-of-3 shares)
ethernity backup secrets.txt -o backup.pdf --shard-threshold 2 --shard-count 3
```

You'll be prompted for a passphrase. **Remember this passphrase**—it's required for recovery.

### Generate the Recovery Kit

```bash
ethernity kit -o recovery_kit.pdf
```

Print `recovery_kit.pdf` and store it with your backups. This contains the offline recovery tool as QR codes.

### Recover Your Files

1. Scan the recovery kit QR codes and open the HTML file in a browser
2. Scan your backup QR codes and paste the data
3. Enter your passphrase
4. Download your recovered files

Or use the CLI:

```bash
ethernity recover backup.pdf -o recovered/
```

---

## CLI Reference

```
ethernity backup <FILES>     Create an encrypted backup
ethernity recover <PDF>      Recover files from a backup
ethernity kit                Generate the recovery kit PDF
ethernity keys generate      Generate a new signing key pair
ethernity keys recover       Recover signing keys from backup
```

### Common Options

| Option | Description |
|--------|-------------|
| `-o, --output` | Output file path |
| `-p, --paper` | Paper size: A4 (default) or LETTER |
| `-c, --config` | Custom configuration file |
| `-q, --quiet` | Suppress non-error output |

### Backup Options

| Option | Description |
|--------|-------------|
| `--shard-threshold` | Minimum shares needed to recover (e.g., 2 for "2-of-3") |
| `--shard-count` | Total number of shares to create (e.g., 3 for "2-of-3") |
| `--skip-auth-check` | Skip signature verification during recovery |

Run `ethernity <command> --help` for detailed option information.

---

## Secret Sharing

For high-value backups, you can split the passphrase into multiple shares using [Shamir's Secret Sharing](https://en.wikipedia.org/wiki/Shamir%27s_secret_sharing):

```bash
# Create a backup requiring 2 of 3 shares
ethernity backup secrets.txt --shard-threshold 2 --shard-count 3
```

This generates:
- One encrypted backup PDF
- Three separate shard PDFs (give one to each trusted person)

To recover, you need:
- The encrypted backup
- Any 2 of the 3 shard PDFs
- The recovery kit

No single person (including you) can recover the backup alone.

---

## Security

### Encryption

- **Algorithm**: age encryption with scrypt key derivation
- **Work factor**: High scrypt parameters to resist brute-force attacks
- **Integrity**: HMAC-based authentication detects tampering

### What Ethernity Protects Against

- ✅ Data loss from hardware failure
- ✅ Cloud service shutdown or account lockout
- ✅ Digital storage degradation over time
- ✅ Casual physical theft (encrypted)

### What Ethernity Does NOT Protect Against

- ❌ Weak passphrases (use a strong, memorable passphrase)
- ❌ Losing both the backup AND the passphrase
- ❌ Physical destruction of all paper copies
- ❌ Targeted attacks with physical access and rubber-hose cryptanalysis

### Best Practices

1. **Use a strong passphrase**: 4+ random words or 20+ characters
2. **Store copies in multiple locations**: Different buildings, cities, or with trusted people
3. **Use secret sharing for critical data**: No single point of failure
4. **Test your backups**: Periodically verify you can recover
5. **Protect the paper**: Use acid-free paper, lamination, or fireproof storage

---

## Development

### Setup

```bash
git clone https://github.com/your-org/ethernity.git
cd ethernity

# Install with dev dependencies
uv sync --extra dev

# Install pre-commit hooks
uv run pre-commit install
```

### Running Tests

```bash
# All tests
uv run pytest

# With coverage
uv run pytest --cov=ethernity --cov-report=html

# Specific test suites
uv run pytest tests/unit
uv run pytest tests/integration
```

### Code Quality

```bash
# Linting and formatting
uv run ruff check src tests
uv run ruff format src tests

# Type checking
uv run mypy src
```

### Building the Recovery Kit

The recovery kit is a self-contained HTML application. To rebuild after changes:

```bash
cd kit
npm install
node build_kit.mjs
```

The bundle is output to `src/ethernity/kit/recovery_kit.bundle.html`.

---

## Architecture

```
ethernity/
├── cli/            # Command-line interface (Typer)
├── config/         # Configuration loading and defaults
├── crypto/         # Encryption (age) and signing
├── encoding/       # QR encoding/decoding, framing protocol
├── formats/        # Envelope format, manifest structure
├── qr/             # QR code generation and scanning
├── render/         # PDF rendering (Jinja2 templates)
└── kit/            # Recovery kit bundle

kit/
├── app/            # Preact application
├── lib/            # Crypto libraries (age, zip)
└── build_kit.mjs   # Bundle builder
```

---

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests and linting (`uv run pytest && uv run ruff check src tests`)
5. Commit your changes (`git commit -m 'Add amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

---

## License

MIT License - see [LICENSE](LICENSE) for details.

---

## Acknowledgments

- [age](https://age-encryption.org/) - Modern encryption tool
- [Shamir's Secret Sharing](https://en.wikipedia.org/wiki/Shamir%27s_secret_sharing) - Threshold cryptography
- [Preact](https://preactjs.com/) - Lightweight React alternative for the recovery kit
- [segno](https://github.com/heuer/segno) - QR code generation

---

<p align="center">
  <strong>Your data. Your control. Forever.</strong>
</p>
