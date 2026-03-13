# CLI API

Ethernity exposes a machine-readable CLI surface for GUI and automation clients under
`ethernity api`.

Current commands:

- `ethernity api backup`
- `ethernity api recover`
- `ethernity api kit`
- `ethernity api settings get`
- `ethernity api settings set`

These commands write newline-delimited JSON (NDJSON) to `stdout`. In API mode, treat `stdout` as
reserved for event records only.

`ethernity api recover` does not implicitly read stdin. To recover from stdin, pass
`--fallback-file -` explicitly.

## Contract

- Schema version: `1`
- JSON Schema file: `docs/cli_api.schema.json`
- Transport: one JSON object per line on `stdout`
- Encoding: UTF-8 text
- Files and large artifacts: written to disk, then referenced by path in emitted events
- Exit code `0`: success
- Exit code `2`: validation, input, configuration, or runtime failure
- Exit code `130`: cancelled by user

## Event Types

### `started`

Emitted once at command start.

Fields:

- `type`: `started`
- `schema_version`: integer
- `command`: `backup`, `recover`, or `kit`
- `args`: sanitized argument summary

For `backup`, `args.passphrase_generate` reflects whether the command will generate a passphrase,
not only whether `--generate-passphrase` was explicitly provided.

### `phase`

Emitted when the command enters a new stage.

Fields:

- `type`: `phase`
- `id`: stable phase id
- `label`: human-readable stage label

Current phases:

- Backup: `plan`, `input`, `backup`, `prepare`, `encrypt`, `shard`, `render`
- Recover: `plan`, `decrypt`, `write`
- Recovery kit: `plan`, `render`

### `progress`

Emitted for countable or completed work inside a phase.

Fields:

- `type`: `progress`
- `phase`: owning phase id
- `current`: completed units
- `total`: total units when known, otherwise `null`
- `unit`: unit label such as `files`, `documents`, or `step`
- `label`: optional progress label
- `details`: optional structured metadata

### `warning`

Emitted for non-fatal conditions.

Fields:

- `type`: `warning`
- `code`: stable warning code
- `message`: human-readable warning
- `details`: optional structured metadata

### `artifact`

Emitted for each output file produced by the command.

Fields:

- `type`: `artifact`
- `kind`: stable artifact kind
- `path`: normalized filesystem path for the emitted artifact
- `details`: optional metadata such as filename, size, hashes, or manifest path

### `result`

Emitted once on success.

Fields:

- `type`: `result`
- `ok`: `true`
- command-specific payload

Backup results expose `generated_passphrase` only when Ethernity generated the passphrase for the
run. Caller-supplied passphrases are not echoed back into NDJSON output.

Result path fields use the same normalized path form as the corresponding artifact events.

### `error`

Emitted once on failure.

Fields:

- `type`: `error`
- `ok`: `false`
- `code`: stable error code
- `message`: human-readable error
- `details`: optional structured metadata

## Stable Error Codes

Current command-specific error codes:

- `INPUT_REQUIRED`: `ethernity api backup` was invoked without `--input`, `--input-dir`, or
  `--input -`
- `OUTPUT_REQUIRED`: `ethernity api recover` was invoked without `--output`
- `SHARD_DIR_NOT_FOUND`: `--shard-dir` path does not exist
- `SHARD_DIR_INVALID`: `--shard-dir` path is not a directory
- `SHARD_DIR_EMPTY`: `--shard-dir` contains no `.txt` files

Current generic error codes:

- `CANCELLED`
- `NOT_FOUND`
- `PERMISSION_DENIED`
- `INVALID_INPUT`
- `RUNTIME_ERROR`
- `IO_ERROR`

## Stable Warning Codes

Current warning codes emitted by backup/recover flows:

- `AUTH_PAYLOAD_MISSING`
- `AUTH_PAYLOAD_INVALID`
- `AUTH_DOC_HASH_MISMATCH`
- `AUTH_SIGNATURE_INVALID`
- `AUTH_FALLBACK_INVALID`
- `FALLBACK_SECTION_INVALID`
- `NON_FALLBACK_LINES_SKIPPED`
- `RECOVERY_SHARD_PAYLOADS_IGNORED`
- `BACKUP_SIGNING_KEY_SHARDING_DISABLED`
- `BACKUP_QR_CHUNK_SIZE_REDUCED`

Additional warning and error codes may be added in a backwards-compatible way. Existing codes will
remain stable once documented here.

## Artifact Kinds

Current artifact kinds:

- Backup: `qr_document`, `recovery_document`, `recovery_kit_index`, `shard_document`,
  `signing_key_shard_document`, `layout_debug_json`
- Recover: `recovered_file`
- Recovery kit: `recovery_kit_qr_document`

When `ethernity api backup --layout-debug-dir <dir>` is used, each generated layout sidecar is
emitted as an `artifact` event with kind `layout_debug_json`.

## Example

```json
{"type":"started","schema_version":1,"command":"recover","args":{"payloads_file":"main_payloads.txt","has_passphrase":true}}
{"type":"phase","id":"plan","label":"Resolving recovery inputs"}
{"type":"progress","phase":"plan","current":1,"total":1,"unit":"step","details":{"main_frame_count":2,"auth_frame_count":1,"shard_frame_count":0}}
{"type":"phase","id":"decrypt","label":"Decrypting and extracting payload"}
{"type":"artifact","kind":"recovered_file","path":"/tmp/out/secret.txt","details":{"manifest_path":"secret.txt","size":42}}
{"type":"result","ok":true,"command":"recover","output_path":"/tmp/out/secret.txt"}
```

## Client Guidance

- Parse events line-by-line as they arrive
- Ignore unknown fields for forward compatibility
- Handle unknown event codes as non-fatal unless the event type is `error`
- For `recover`, the main recovery input still must be exactly one of `--fallback-file`,
  `--payloads-file`, or `--scan`, but shard file inputs may be recovery text, QR payload text,
  or shard PDFs/images under the existing shard file flags
- Use artifact paths rather than assuming output filenames
- Prefer `code` values for logic and `message` values for display
- Treat stdin as opt-in for `api recover`; pass `--fallback-file -` when piping recovery text
