# Frozen v1.0 golden backups

This directory contains committed backup outputs for the stable v1.0 baseline.

Frozen sets are split by QR transport profile:

- `base64/`: backups from the run that requested `qr_payload_codec=base64`
- `raw/`: backups from the run that requested `qr_payload_codec=raw`

Historical note: the committed PDFs in both folders contain raw frame bytes. The `base64` folder
name and index value record the requested builder setting, but the old builder rewrote a commented
example instead of the active TOML value. These released bytes stay frozen. Current base64 output
is tested by the live producer round trip rather than inferred from this mislabeled fixture folder.

Each profile folder contains its own `index.json` and scenario subfolders.

The frozen suite verifies every committed file hash, payload pair, shard format, and restore
scenario for both transports. PDF decoding is reused by content hash within a run. The complete
replacement option matrix runs against raw transport; a sharded embedded-signing case verifies the
same producer/scanner path under base64 without repeating the full Cartesian product. Multi-step
replacement scenarios are assigned to one transport/version combination per distinct guarantee.
Current backup creation is owned by `tests/e2e/test_end_to_end_v1_baseline.py`, including all five
input/sharding modes in raw transport and a separate base64 producer/scan/restore check.

Each scenario folder includes:

- `backup/*.pdf`: frozen generated documents (`qr_document`, `recovery_document`,
  `recovery_kit_index`, and shard/signing-shard PDFs when applicable)
- `main_payloads.txt`: scanned QR payload lines from `qr_document.pdf`
- `main_payloads.bin`: scanned QR payload bytes in deterministic binary framing
- `shard_payloads_threshold.txt`: scanned shard payload lines at threshold size (sharded scenarios)
- `shard_payloads_threshold.bin`: scanned shard payload bytes in deterministic binary framing
  (sharded scenarios)
- `snapshot.json`: recorded document and shard fields, expected recovered file hashes, and file hashes

Top-level `index.json` maps profile names to profile index paths.

## Regeneration

These committed outputs are historical compatibility files. Do not
regenerate them for routine implementation, CLI, or renderer migrations. Only
replace them as an intentional fixture-version change after reviewing file
hash diffs and proving that old backups still restore.

Regenerate all frozen sets from `tests/fixtures/v1_0/source` only for that
intentional fixture-version work:

```sh
uv run python tests/fixtures/v1_0/golden/build_golden.py
```

This command is destructive for this folder: existing scenario outputs are
replaced.
