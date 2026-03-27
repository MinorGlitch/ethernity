# CLI API

Ethernity exposes a machine-readable CLI surface for GUI and automation clients under
`ethernity api`.

Current commands:

- `ethernity api backup`
- `ethernity api config get`
- `ethernity api config set`
- `ethernity api inspect mint`
- `ethernity api inspect recover`
- `ethernity api mint`
- `ethernity api recover`

These commands write newline-delimited JSON (NDJSON) to `stdout`. In API mode, treat `stdout` as
reserved for event records only.

When `--config` is omitted in API mode, command behavior depends on the surface:

- `api backup`, `api mint`, and `api recover` load defaults from the existing user config when it
  already exists, otherwise they fall back to the packaged config without creating user config
  files.
- `api config get` targets the user config path by default but does not initialize it just to read
  settings.
- `api config set` targets the user config path by default and will initialize it if needed.

`ethernity api recover` does not implicitly read stdin. To recover from stdin, pass
`--fallback-file -` for fallback text or `--payloads-file -` for QR payload lines.

## Contract

- Schema version: `1`
- JSON Schema file: `docs/cli_api.schema.json`
- Transport: one JSON object per line on `stdout`
- Encoding: UTF-8 text
- Files and large artifacts: written to disk, then referenced by path in emitted events
- Inspect commands do not write files and never emit `artifact` events
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

For `api inspect recover` and `api inspect mint`, `args.operation` is `inspect` while `command`
remains `recover` or `mint`.

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
an output directory path. When `--output` points to an existing directory, single-file recovery is
written inside that directory using the manifest filename.

For `api backup`, if `--output-dir` points to an existing directory, it is treated as a parent
directory and Ethernity creates `backup-<doc_id>` inside it. If the path does not exist, Ethernity
creates that exact directory.

For `api mint`, if `--output-dir` points to an existing directory, it is treated as a parent
directory and Ethernity creates `mint-<doc_id>` inside it. If the path does not exist, Ethernity
creates that exact directory.

Mint results include `signing_key_source` and a stable `artifacts` object for minted shard paths.

Inspect results include `operation: "inspect"`, never include artifacts, and report readiness as a
success-shaped payload: `ok: true` plus any `blocking_issues`.

Decrypt-dependent `source_summary` fields may be `null` until auth or unlock requirements are
satisfied.

Config results include the resolved config path, normalized editable values, supported option
lists, onboarding metadata, and a config validity status so a GUI can build its own onboarding flow
and repair invalid config files.

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

Inspect commands never emit `artifact` events.

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

## Inspect Surfaces

`ethernity api inspect recover` reports:

- `doc_id`, `input_label`, `input_detail`, `auth_status`
- `source_summary` when decryption is possible, otherwise `null`
- `frame_counts.main|auth|shard`
- `unlock.mode|passphrase_provided|validated_shard_count|required_shard_threshold|satisfied`
- `blocking_issues` and `warnings`

`ethernity api inspect mint` reports:

- `doc_id`, `input_label`, `input_detail`, `auth_status`
- `source_summary` when decryption is possible, otherwise `null`
- `frame_counts.main|auth|shard|signing_key_shard`
- `unlock.validated_passphrase_shard_count|required_passphrase_threshold|satisfied`
- `signing_key.validated_shard_count|required_threshold|satisfied|source`
- `mint_capabilities.can_mint_passphrase_shards|can_mint_signing_key_shards`
- `blocking_issues` and `warnings`

`frame_counts.signing_key_shard` reports decoded signing-key shard input frames. Signing-key
readiness comes from `signing_key.satisfied`; `validated_shard_count` is informational and can be
`0` when the backup already embeds a signing seed. `unlock.satisfied` is `false` whenever auth
validation is blocking even if shard quorum is otherwise met.

`mint_capabilities` is per output type and reflects both readiness and the currently enabled
output toggles. A replacement-shard blocker can disable one capability while leaving the other
available.

When `ethernity api backup --layout-debug-dir <dir>` is used, each generated layout sidecar is
emitted as an `artifact` event with kind `layout_debug_json`.

## Config Surface

`api config get` and `api config set` expose a structured editable config model with these sections:

- `templates.default_name`
- `templates.template_name`, `templates.recovery_template_name`,
  `templates.shard_template_name`, `templates.signing_key_shard_template_name`,
  `templates.kit_template_name`
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
though `ethernity api recover` still requires explicit `--output`. When `onboarding` is supplied,
`onboarding.mark_complete` must be set explicitly.

Config results also include:

- `status`: `valid`, `invalid_toml`, or `invalid_values`
- `errors`: structured load problems for the current config snapshot

When `status` is not `valid`, `values` still contain a schema-valid snapshot derived from defaults
and any parseable settings so the GUI can offer repair UX.

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

If the GUI reads an explicit config file with `--config`, onboarding metadata is not considered
applicable to that file. The result will report `onboarding.needed = false` and an empty
`onboarding.configured_fields` list.

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
When onboarding is marked complete again, the stored `configured_fields` set is replaced with the
new list from the patch.

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
{"type":"started","schema_version":1,"command":"recover","args":{"config":null,"paper":null,"fallback_file":null,"payloads_file":"main_payloads.txt","scan":[],"has_passphrase":true,"shard_fallback_file":[],"shard_payloads_file":[],"shard_scan":[],"auth_fallback_file":null,"auth_payloads_file":null,"output":"/tmp/out/secret.txt","allow_unsigned":false,"quiet":true,"debug":false}}
{"type":"phase","id":"plan","label":"Resolving recovery inputs"}
{"type":"progress","phase":"plan","current":1,"total":1,"unit":"step","details":{"main_frame_count":2,"auth_frame_count":1,"shard_frame_count":0}}
{"type":"phase","id":"decrypt","label":"Decrypting and extracting payload"}
{"type":"artifact","kind":"recovered_file","path":"/tmp/out/secret.txt","details":{"manifest_path":"secret.txt","size":42}}
{"type":"result","ok":true,"command":"recover","output_path":"/tmp/out/secret.txt","output_path_kind":"file","doc_id":"deadbeef","auth_status":"verified","input_label":"QR payloads","input_detail":"main_payloads.txt","manifest":{"format_version":1,"input_origin":"file","input_roots":["secret.txt"],"sealed":true,"file_count":1,"payload_codec":"raw","payload_raw_len":42},"files":[{"manifest_path":"secret.txt","output_path":"/tmp/out/secret.txt","size":42,"sha256":"0123","mtime":0}]}
```

```json
{"type":"started","schema_version":1,"command":"recover","args":{"operation":"inspect","config":null,"paper":null,"fallback_file":null,"payloads_file":"main_payloads.txt","scan":[],"has_passphrase":false,"shard_fallback_file":["shard-1.txt"],"shard_payloads_file":[],"shard_scan":[],"auth_fallback_file":null,"auth_payloads_file":null,"allow_unsigned":false,"quiet":true,"debug":false}}
{"type":"phase","id":"plan","label":"Resolving recovery inputs"}
{"type":"progress","phase":"plan","current":1,"total":1,"unit":"step","details":{"main_frame_count":2,"auth_frame_count":0,"shard_frame_count":1}}
{"type":"phase","id":"decrypt","label":"Decrypting and extracting payload"}
{"type":"progress","phase":"decrypt","current":1,"total":1,"unit":"step","details":{"output_path":null,"output_path_kind":"none"}}
{"type":"result","ok":true,"command":"recover","operation":"inspect","doc_id":"deadbeef","auth_status":"missing","input_label":"QR payloads","input_detail":"main_payloads.txt","source_summary":null,"frame_counts":{"main":2,"auth":0,"shard":1},"unlock":{"mode":"shards","passphrase_provided":false,"validated_shard_count":1,"required_shard_threshold":2,"satisfied":false},"blocking_issues":[{"code":"PASSPHRASE_SHARDS_UNDER_QUORUM","message":"need at least 2 shard(s) to recover passphrase","details":{"provided_count":1,"required_threshold":2}}],"warnings":[]}
```

```json
{"type":"started","schema_version":1,"command":"config","args":{"operation":"get","config":null,"input_json":null}}
{"type":"phase","id":"load","label":"Loading config"}
{"type":"result","ok":true,"command":"config","operation":"get","path":"/home/user/.config/ethernity/config.toml","source":"user","status":"valid","errors":[],"values":{"templates":{"default_name":"sentinel","template_name":null,"recovery_template_name":null,"shard_template_name":null,"signing_key_shard_template_name":null,"kit_template_name":null},"page":{"size":"A4"},"qr":{"error":"M","chunk_size":512},"defaults":{"backup":{"base_dir":null,"output_dir":null,"shard_threshold":null,"shard_count":null,"signing_key_mode":null,"signing_key_shard_threshold":null,"signing_key_shard_count":null,"payload_codec":"auto","qr_payload_codec":"raw"},"recover":{"output":null}},"ui":{"quiet":false,"no_color":false,"no_animations":false},"debug":{"max_bytes":1024},"runtime":{"render_jobs":"auto"}},"options":{"template_designs":["archive","forge","ledger","maritime","sentinel"],"page_sizes":["A4","LETTER"],"qr_error_correction":["L","M","Q","H"],"payload_codecs":["auto","raw","gzip"],"qr_payload_codecs":["raw","base64"],"signing_key_modes":["embedded","sharded"],"onboarding_fields":["template_design","page_size","backup_output_dir","qr_chunk_size","qr_error_correction","sharding","payload_codec","qr_payload_codec"]},"onboarding":{"needed":true,"configured_fields":[],"available_fields":["template_design","page_size","backup_output_dir","qr_chunk_size","qr_error_correction","sharding","payload_codec","qr_payload_codec"]}}
```

Recover can also scan QR payloads directly from PDFs, images, or directories by using `--scan`:

```bash
ethernity api recover --scan "/path/to/recovery_document.pdf" --passphrase "correct horse battery staple" --output "/tmp/recovered.bin"
```

Passphrase shard PDFs/images can be scanned separately with `--shard-scan`:

```bash
ethernity api recover --scan "/path/to/qr_document.pdf" --shard-scan "/path/to/shard-01.pdf" --shard-scan "/path/to/shard-02.pdf" --output "/tmp/recovered.bin"
```

## Client Guidance

- Parse events line-by-line as they arrive
- Ignore unknown fields for forward compatibility
- Handle unknown event codes as non-fatal unless the event type is `error`
- Treat artifact events as success-only notifications; a failed command may still have written files
- Use artifact paths rather than assuming output filenames
- Use `output_path_kind` to distinguish file outputs from directory outputs
- Treat inspect `blocking_issues` as readiness guidance, not command failure
- Use `api config get/set` for GUI settings management and onboarding state
- Expect `api backup` / `api mint` / `api recover` to use the existing user config when present
- Expect `api inspect recover` / `api inspect mint` to avoid file writes and artifact events
- Prefer `code` values for logic and `message` values for display
- Treat stdin as opt-in for `api recover`; pass `--fallback-file -` for recovery text or `--payloads-file -` for QR payload lines
