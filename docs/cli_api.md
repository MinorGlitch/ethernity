# CLI API

Ethernity exposes a machine-readable CLI surface for GUI and automation clients under
`ethernity api`.

Current commands:

- `ethernity api backup`
- `ethernity api config get`
- `ethernity api config set`
- `ethernity api mint`
- `ethernity api recover`

These commands write newline-delimited JSON (NDJSON) to `stdout`. In API mode, treat `stdout` as
reserved for event records only.

When `--config` is omitted in API mode, command behavior depends on the surface:

- `api backup`, `api mint`, and `api recover` load defaults from the existing user config when it
  already exists, otherwise they fall back to the packaged config without creating user config
  files.
- `api config get` and `api config set` target the user config by default and will initialize it if
  needed.

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
- `command`: `backup`, `config`, `mint`, or `recover`
- `args`: sanitized argument summary

For `backup`, `args.passphrase_generate` reflects whether the command will generate a passphrase,
not only whether `--generate-passphrase` was explicitly provided.

The `args` payload is command-specific and schema-validated in `docs/cli_api.schema.json`.

For `config`, `args.operation` is `get` or `set`.

### `phase`

Emitted when the command enters a new stage.

Fields:

- `type`: `phase`
- `id`: stable phase id
- `label`: human-readable stage label

Current phases:

- Backup: `plan`, `input`, `backup`, `prepare`, `encrypt`, `shard`, `render`
- Config: `load`, `validate`, `write`
- Mint: `plan`, `mint`, `render`
- Recover: `plan`, `decrypt`, `write`

### `progress`

Emitted for countable or completed work inside a phase.

Fields:

- `type`: `progress`
- `phase`: owning phase id
- `current`: completed units
- `total`: total units when known, otherwise `null`
- `unit`: unit label such as `files`, `documents`, or `step`
- `label`: progress label or `null`
- `details`: structured metadata object, possibly empty

### `warning`

Emitted for non-fatal conditions.

Fields:

- `type`: `warning`
- `code`: stable warning code
- `message`: human-readable warning
- `details`: structured metadata object, possibly empty

### `artifact`

Emitted for each output file produced by the command after the command completes successfully.

Fields:

- `type`: `artifact`
- `kind`: stable artifact kind
- `path`: normalized filesystem path for the emitted artifact
- `details`: structured metadata object, possibly empty

### `result`

Emitted once on success.

Fields:

- `type`: `result`
- `ok`: `true`
- command-specific payload

Backup results expose `generated_passphrase` only when Ethernity generated the passphrase for the
run. Caller-supplied passphrases are not echoed back into NDJSON output.

Result path fields use the same normalized path form as the corresponding artifact events.

Recover results include `output_path_kind` so clients can distinguish a single recovered file from
an output directory path.

Mint results include `signing_key_source` and a stable `artifacts` object for minted shard paths.

Config results include the resolved config path, normalized editable values, supported option
lists, and onboarding metadata so a GUI can build its own onboarding flow.

### `error`

Emitted once on failure.

Fields:

- `type`: `error`
- `ok`: `false`
- `code`: stable error code
- `message`: human-readable error
- `details`: structured metadata object, possibly empty

## Stable Error Codes

Current command-specific error codes:

- `INPUT_REQUIRED`: `ethernity api backup` was invoked without `--input`, `--input-dir`, or
  `--input -`
- `OUTPUT_REQUIRED`: `ethernity api recover` was invoked without `--output`
- `CONFIG_INPUT_REQUIRED`: `ethernity api config set` was invoked without `--input-json`
- `CONFIG_JSON_INVALID`: the JSON patch passed to `api config set` was malformed or not an object
- `CONFIG_UNKNOWN_FIELD`: the patch referenced an unsupported config or onboarding field
- `CONFIG_INVALID_VALUE`: the patch supplied a value with the wrong type or enum value
- `CONFIG_CONFLICT`: the patch supplied conflicting settings (for example mismatched shard counts)
- `SHARD_DIR_NOT_FOUND`: `--shard-dir` path does not exist
- `SHARD_DIR_INVALID`: `--shard-dir` path is not a directory
- `SHARD_DIR_EMPTY`: `--shard-dir` contains no `.txt` files
- `SIGNING_KEY_SHARD_DIR_NOT_FOUND`: `--signing-key-shard-dir` path does not exist
- `SIGNING_KEY_SHARD_DIR_INVALID`: `--signing-key-shard-dir` path is not a directory
- `SIGNING_KEY_SHARD_DIR_EMPTY`: `--signing-key-shard-dir` contains no `.txt` files

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
- Mint: `shard_document`, `signing_key_shard_document`, `layout_debug_json`
- Recover: `recovered_file`

## Phase IDs

Stable phase ids currently emitted by the API:

- Backup: `plan`, `input`, `backup`, `prepare`, `encrypt`, `shard`, `render`
- Config: `load`, `validate`, `write`
- Mint: `plan`, `mint`, `render`
- Recover: `plan`, `decrypt`, `write`

## Recover Auth Status

Stable recover `result.auth_status` values:

- `verified`
- `skipped`
- `missing`
- `invalid`
- `ignored`

When `ethernity api backup --layout-debug-dir <dir>` is used, each generated layout sidecar is
emitted as an `artifact` event with kind `layout_debug_json`.

## Config Surface

`api config get` and `api config set` expose a structured editable config model with these sections:

- `templates.default_name`
- `page.size`
- `qr.error`, `qr.chunk_size`
- `defaults.backup.*`
- `defaults.recover.output`
- `ui.*`
- `debug.max_bytes`
- `runtime.render_jobs`

Config results also expose onboarding metadata:

- `onboarding.needed`
- `onboarding.configured_fields`
- `onboarding.available_fields`

`api config set` accepts a partial JSON patch with this shape:

```json
{
  "values": {
    "page": {"size": "LETTER"},
    "defaults": {"backup": {"output_dir": "/tmp/backups"}}
  },
  "onboarding": {
    "mark_complete": true,
    "configured_fields": ["page_size", "backup_output_dir"]
  }
}
```

Unknown patch fields are rejected. `defaults.recover.output` remains an editable config value even
though `ethernity api recover` still requires explicit `--output`.

## GUI Onboarding Procedure

The GUI should build its own onboarding flow on top of `api config get` and `api config set`.
Ethernity does not expose a separate API wizard.

Recommended procedure:

1. Call `ethernity api config get`.
2. Read `result.onboarding.needed`, `result.onboarding.configured_fields`, `result.options`, and
   the current `result.values` snapshot.
3. Render the GUI's own onboarding steps and prefill any existing values you want to preserve.
4. Submit a partial patch with `ethernity api config set --input-json <file>`.
5. Include `onboarding.mark_complete = true` and set `onboarding.configured_fields` to the fields
   your GUI actually collected during onboarding.
6. Optionally call `ethernity api config get` again to confirm the saved state.

Current onboarding field identifiers map to config values like this:

- `template_design` -> `templates.default_name`
- `page_size` -> `page.size`
- `backup_output_dir` -> `defaults.backup.output_dir`
- `qr_chunk_size` -> `qr.chunk_size`
- `qr_error_correction` -> `qr.error`
- `payload_codec` -> `defaults.backup.payload_codec`
- `qr_payload_codec` -> `defaults.backup.qr_payload_codec`
- `sharding` -> `defaults.backup.shard_threshold`, `defaults.backup.shard_count`,
  `defaults.backup.signing_key_mode`, `defaults.backup.signing_key_shard_threshold`, and
  `defaults.backup.signing_key_shard_count`

The onboarding marker is separate from the TOML config file. `onboarding.configured_fields`
describes what the GUI asked the user during onboarding, not every value present in the config.

Example onboarding patch:

```json
{
  "values": {
    "templates": {"default_name": "forge"},
    "page": {"size": "LETTER"},
    "qr": {"error": "Q", "chunk_size": 384},
    "defaults": {
      "backup": {
        "output_dir": "/tmp/backups",
        "payload_codec": "auto",
        "qr_payload_codec": "raw",
        "shard_threshold": 2,
        "shard_count": 3,
        "signing_key_mode": "sharded",
        "signing_key_shard_threshold": 2,
        "signing_key_shard_count": 3
      }
    }
  },
  "onboarding": {
    "mark_complete": true,
    "configured_fields": [
      "template_design",
      "page_size",
      "backup_output_dir",
      "qr_chunk_size",
      "qr_error_correction",
      "payload_codec",
      "qr_payload_codec",
      "sharding"
    ]
  }
}
```

## Example

```json
{"type":"started","schema_version":1,"command":"recover","args":{"payloads_file":"main_payloads.txt","has_passphrase":true}}
{"type":"phase","id":"plan","label":"Resolving recovery inputs"}
{"type":"progress","phase":"plan","current":1,"total":1,"unit":"step","details":{"main_frame_count":2,"auth_frame_count":1,"shard_frame_count":0}}
{"type":"phase","id":"decrypt","label":"Decrypting and extracting payload"}
{"type":"artifact","kind":"recovered_file","path":"/tmp/out/secret.txt","details":{"manifest_path":"secret.txt","size":42}}
{"type":"result","ok":true,"command":"recover","output_path":"/tmp/out/secret.txt","output_path_kind":"file"}
```

```json
{"type":"started","schema_version":1,"command":"config","args":{"operation":"get","config":null,"input_json":null}}
{"type":"phase","id":"load","label":"Loading config"}
{"type":"result","ok":true,"command":"config","operation":"get","path":"/home/user/.config/ethernity/config.toml","source":"user","values":{"page":{"size":"A4"}},"options":{"page_sizes":["A4","LETTER"]},"onboarding":{"needed":true,"configured_fields":[],"available_fields":["page_size"]}}
```

## Client Guidance

- Parse events line-by-line as they arrive
- Ignore unknown fields for forward compatibility
- Handle unknown event codes as non-fatal unless the event type is `error`
- Treat artifact events as success-only notifications; a failed command may still have written files
- Use artifact paths rather than assuming output filenames
- Use `output_path_kind` to distinguish file outputs from directory outputs
- Use `api config get/set` for GUI settings management and onboarding state
- Expect `api backup` / `api mint` / `api recover` to use the existing user config when present
- Prefer `code` values for logic and `message` values for display
- Treat stdin as opt-in for `api recover`; pass `--fallback-file -` when piping recovery text
