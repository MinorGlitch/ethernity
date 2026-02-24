# Frozen v1.0 Golden Backups

This directory contains committed backup outputs for the stable v1.0 baseline.

Each scenario folder includes:

- `backup/*.pdf`: frozen generated documents (`qr_document`, `recovery_document`,
  `recovery_kit_index`, and shard/signing-shard PDFs when applicable)
- `main_payloads.txt`: scanned QR payload lines from `qr_document.pdf`
- `shard_payloads_threshold.txt`: scanned shard payload lines at threshold size (sharded scenarios)
- `snapshot.json`: locked protocol projection, expected recovered file hashes, and artifact hashes

`index.json` is the scenario registry used by e2e tests.

## Regeneration

Regenerate all frozen sets from `tests/fixtures/v1_0/source`:

```sh
uv run python tests/fixtures/v1_0/golden/build_golden.py
```

This is intentional and destructive for this folder: existing scenario outputs are replaced.
