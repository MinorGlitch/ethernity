# Frozen v1.1 Golden Backups

This directory contains committed backup outputs for the shard-payload v2 / stable v1.1 baseline.

Frozen sets are split by QR transport profile:

- `base64/`: backups generated with `qr_payload_codec=base64`
- `raw/`: backups generated with `qr_payload_codec=raw`

Each profile folder contains its own `index.json` and scenario subfolders.

Each scenario folder includes:

- `backup/*.pdf`: frozen generated documents (`qr_document`, `recovery_document`,
  `recovery_kit_index`, and shard/signing-shard PDFs when applicable)
- `main_payloads.txt`: scanned QR payload lines from `qr_document.pdf`
- `main_payloads.bin`: scanned QR payload bytes in deterministic binary framing
- `shard_payloads_threshold.txt`: scanned shard payload lines at threshold size (sharded scenarios)
- `shard_payloads_threshold.bin`: scanned shard payload bytes in deterministic binary framing
  (sharded scenarios)
- `snapshot.json`: locked protocol projection, expected recovered file hashes, and artifact hashes

Top-level `index.json` maps profile names to profile index paths.

This golden family reuses the input corpus from `tests/fixtures/v1_0/source`.

## Regeneration

Regenerate all frozen sets from `tests/fixtures/v1_0/source`:

```sh
uv run python tests/fixtures/v1_1/golden/build_golden.py
```

This is intentional and destructive for this folder: existing scenario outputs are replaced.
