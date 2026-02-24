# Stable v1.0 E2E Test Procedures

This fixture and procedure set defines the release baseline for backup/recovery behavior.

## Fixture Root

- `tests/fixtures/v1_0/source/standalone_secret.txt`
- `tests/fixtures/v1_0/source/mixed_input.txt`
- `tests/fixtures/v1_0/source/directory_payload/alpha.txt`
- `tests/fixtures/v1_0/source/directory_payload/nested/beta.json`
- `tests/fixtures/v1_0/source/directory_payload/nested/raw.bin`

## Covered Profiles

1. No sharding, file input (`input_origin=file`)
2. No sharding, directory input (`input_origin=directory`)
3. No sharding, mixed input (`input_origin=mixed`)
4. Sharded passphrase + embedded signing key
5. Sharded passphrase + sharded signing key

## Required Artifact Assertions

- Always required:
  - `qr_document.pdf`
  - `recovery_document.pdf`
  - `recovery_kit_index.pdf` (tests force `--design forge` to guarantee index support)
- Sharded profiles additionally require:
  - `shard-*.pdf`
- Signing-key-sharded profile additionally requires:
  - `signing-key-shard-*.pdf`

## Restore Procedure Rules

- Main/auth frames are recovered from generated `qr_document.pdf` via `recover --scan`.
- Shard recovery uses payloads scanned from generated shard PDFs and passed via
  `--shard-payloads-file`.
- Restored bytes and relative paths MUST exactly match source fixture inputs for each scenario.
