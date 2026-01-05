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
