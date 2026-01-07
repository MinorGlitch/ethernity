# Ethernity

Create paper backups that you can recover offline.

## Installation

Install from a local checkout:

```bash
pipx install /path/to/ethernity
```

Then run it:

```bash
ethernity --help
```

## Tests

Run the test suite:

```bash
uv run python -m unittest discover -s tests -p "test_*.py"
```

## Packaging (PyInstaller)

Build a standalone CLI for your OS (browsers are downloaded on first run):

```bash
./scripts/build_pyinstaller.sh
```

On Windows (PowerShell):

```powershell
.\scripts\build_pyinstaller.ps1
```

Artifacts land in `dist/ethernity` (or `dist/ethernity.exe` if you switch to one-file).

### Config location

On first run, Ethernity copies its default configs/templates to:

```
~/.config/ethernity/
```

You can edit those files to customize the output.

### Python imports

Prefer the package-level exports when importing from Python:

```python
from ethernity.config import load_app_config
from ethernity.crypto import encrypt_bytes_with_passphrase
from ethernity.render import RenderInputs, render_frames_to_pdf
from ethernity.formats import encode_envelope, EnvelopeManifest
```

### Sharding signing key

For unsealed passphrase backups with sharding enabled, Ethernity embeds the shard signing
seed inside the encrypted envelope manifest by default. If you want stronger separation,
use `--signing-key-mode sharded` to emit separate signing-key shard PDFs and keep the seed
out of the main envelope. You can also set a different quorum for signing-key shards with
`--signing-key-shard-threshold` and `--signing-key-shard-count` (defaults to the passphrase quorum).
