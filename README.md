# Ethernity

Secure, offline-recoverable backup system with QR-based recovery documents.

Create paper backups that you can recover offline using only a web browser.

## Installation

Install from a local checkout:

```bash
pip install /path/to/ethernity
# or with pipx
pipx install /path/to/ethernity
```

Then run it:

```bash
ethernity --help
```

## Quick Start

Create a backup:

```bash
ethernity backup my_files/ -o backup.pdf
```

Generate a recovery kit (offline recovery tool as QR codes):

```bash
ethernity kit -o recovery_kit.pdf
```

Recover from a backup:

```bash
ethernity recover backup.pdf -o recovered_files/
```

## Development

### Setup

```bash
# Clone and install with dev dependencies
git clone https://github.com/your-org/ethernity.git
cd ethernity
uv sync --extra dev

# Install pre-commit hooks
uv run pre-commit install
```

### Tests

Run the test suite:

```bash
# All tests
uv run pytest

# With coverage
uv run pytest --cov=ethernity --cov-report=html

# Specific test categories
uv run pytest tests/unit
uv run pytest tests/integration
```

### Linting and Formatting

```bash
# Check
uv run ruff check src tests
uv run ruff format --check src tests

# Fix
uv run ruff check --fix src tests
uv run ruff format src tests

# Type checking
uv run mypy src
```

### Building the Recovery Kit

The recovery kit is a self-contained HTML file bundled with the package. To rebuild after changes:

```bash
cd kit
npm install
node build_kit.mjs
# Bundle is output to src/ethernity/kit/recovery_kit.bundle.html
```

## Packaging (PyInstaller)

Build a standalone CLI for your OS:

```bash
pip install ".[build]"
pyinstaller --clean --noconfirm ethernity.spec
```

Artifacts land in `dist/ethernity/`.

## Configuration

On first run, Ethernity copies its default configs/templates to:

```
~/.config/ethernity/   # Linux/macOS
%APPDATA%\ethernity\   # Windows
```

You can edit those files to customize the output.

## Python API

```python
from ethernity.config import load_app_config
from ethernity.crypto import encrypt_bytes_with_passphrase
from ethernity.render import RenderInputs, render_frames_to_pdf
from ethernity.formats import encode_envelope, EnvelopeManifest
```

## License

MIT License - see [LICENSE](LICENSE) for details.
