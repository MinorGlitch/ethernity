# Frozen v1.1 golden backups

This directory contains committed backup outputs for the shard-payload v2 changes in stable v1.1.

Frozen sets are split by QR transport profile:

- `base64/`: backups from the run that requested `qr_payload_codec=base64`
- `raw/`: backups from the run that requested `qr_payload_codec=raw`

Historical note: the committed PDFs in both folders contain raw frame bytes. The `base64` folder
name and index value record the requested builder setting, but the old builder rewrote a commented
example instead of the active TOML value. These released bytes stay frozen. Current base64 output
is tested by the live producer round trip rather than inferred from this mislabeled fixture folder.

Each profile folder contains its own `index.json` and only the shard-bearing scenario subfolders.

Each scenario folder includes:

- `backup/*.pdf`: frozen generated documents (`qr_document`, `recovery_document`,
  `recovery_kit_index`, and shard/signing-shard PDFs when applicable)
- `main_payloads.txt`: scanned QR payload lines from `qr_document.pdf`
- `main_payloads.bin`: scanned QR payload bytes in deterministic binary framing
- `shard_payloads_threshold.txt`: scanned shard payload lines at threshold size (sharded scenarios)
- `shard_payloads_threshold.bin`: scanned shard payload bytes in deterministic binary framing
  (sharded scenarios)
- `signing_key_shard_payloads_threshold.txt`: scanned signing-key shard payload lines at threshold
  size (signing-sharded scenarios)
- `signing_key_shard_payloads_threshold.bin`: scanned signing-key shard payload bytes in
  deterministic binary framing (signing-sharded scenarios)
- `snapshot.json`: recorded document and shard fields, expected recovered file hashes, and file hashes

This family intentionally reuses v1.0 for non-sharded coverage and keeps only the scenarios needed
to check the shard format changes. The frozen shard fixtures assert that decoded backup shard PDFs
carry `version == 2` and `set_id` values, and that the decoded shard records stored in
`snapshot.json` continue to match the committed PDFs. The shard `.bin` wrappers are also kept and
must decode to the same shard values as the threshold text/PDF fixtures.

Top-level `index.json` maps profile names to profile index paths.

This golden family reuses the input corpus from `tests/fixtures/v1_0/source`.

The frozen suite verifies every committed file hash, payload pair, shard format, and restore
scenario for both transports. PDF decoding is reused by content hash within a run. The complete
replacement option matrix runs against raw transport; a sharded embedded-signing case verifies the
same producer/scanner path under base64. Multi-step replacement and mixed-set rejection scenarios
run once for each distinct v1.1 guarantee. Transport decoding remains covered by the complete
frozen matrix and the current-producer baseline.

## Regeneration

These committed outputs are historical compatibility files. Do not
regenerate them for routine implementation, CLI, or renderer migrations. Only
replace them as an intentional fixture-version change after reviewing file
hash diffs and proving that old backups still restore.

Regenerate all frozen sets from `tests/fixtures/v1_0/source` only for that
intentional fixture-version work:

```sh
uv run python tests/fixtures/v1_1/golden/build_golden.py
```

This command is destructive for this folder: existing scenario outputs are
replaced.
