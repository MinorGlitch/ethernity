# CLI API

Ethernity exposes a machine-readable CLI surface for GUI and automation clients under
`ethernity api`.

Current commands:

- `ethernity api backup`
- `ethernity api compact`
- `ethernity api config get`
- `ethernity api config set`
- `ethernity api extend`
- `ethernity api inspect mint`
- `ethernity api inspect extend`
- `ethernity api inspect recover`
- `ethernity api mint`
- `ethernity api recover`

These commands write newline-delimited JSON (NDJSON) to `stdout`. In API mode, treat `stdout` as
reserved for event records only.

When `--config` is omitted in API mode, command behavior depends on the surface:

- `api backup`, `api compact`, `api extend`, `api mint`, and `api recover` load defaults from the
  existing user config when it already exists, otherwise they fall back to the packaged config
  without creating user config files.
- `api config get` uses the user config when it exists; otherwise it reports the packaged config
  path with `source = "default"` and does not initialize user config just to read settings.
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
- `command`: `backup`, `compact`, `config`, `extend`, `mint`, or `recover`
- `args`: sanitized argument summary

For `backup`, `args.passphrase_generate` reflects whether the command will generate a passphrase,
not only whether `--generate-passphrase` was explicitly provided.

The `args` payload is command-specific and schema-validated in `docs/cli_api.schema.json`.

For `config`, `args.operation` is `get` or `set`.

For `api inspect recover`, `api inspect extend`, and `api inspect mint`, `args.operation` is
`inspect` while `command` remains `recover`, `extend`, or `mint`.

### `phase`

Emitted when the command enters a new stage.

Fields:

- `type`: `phase`
- `id`: stable phase id
- `label`: human-readable stage label

Current phases:

- Backup: `plan`, `input`, `backup`, `prepare`, `encrypt`, `shard`, `render`
- Compact: `compact`
- Config: `load`, `validate`, `write`
- Extend: `plan`, `render`, `validate`, `publish`
- Extend inspect: `plan`
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

Mint results include `doc_hash`, `selected_extension_index`, `selected_extension_doc_hash`,
`expected_head_doc_hash`, `validated_head_index`, `validated_head_doc_hash`, `freshness_scope`,
`signing_key_source`, and a stable `artifacts` object for minted shard paths.
Minting from an imported root-plus-extension recovery set requires either
`--expected-head-doc-hash` or `--allow-stale-head` because the supplied carriers prove only the
freshest head among the supplied inputs.

Compact results include `expected_head_doc_hash`, `validated_head_index`,
`validated_head_doc_hash`, and `freshness_scope` for the source head that was flattened into the
new standalone backup. Scan-mode compact requires either `--expected-head-doc-hash` or
`--allow-stale-head` because scanned carriers prove only the freshest head among supplied inputs.

Extend results include `index`, `doc_id`, `doc_hash`, `root_doc_id`, `root_doc_hash`, `chain_id`,
`parent_head_index`, `parent_head_doc_hash`, `expected_head_doc_hash`, `freshness_scope`, the
promoted `extension_dir`, a stable `artifacts` object for generated PDFs, and execution summaries
for `selected_scope`, `diff_summary`, `resolved_policy`, `chunk_reuse`, and `extension_bytes`.

Successful extend results always include non-null root lineage (`root_doc_id`, `root_doc_hash`,
`chain_id`), selected-scope metadata, diff metadata, and chunk-reuse statistics. Missing readiness
metadata is reported as an error before publishing instead of being represented as a partial success.

Extend `selected_scope` uses a stable scope summary with `files`, `directories`, `base_dir`,
`file_count`, `total_bytes`, `input_origin`, and `input_roots`. Extend `diff_summary` includes
`new_paths`, `changed_paths`, `unchanged_paths`, `missing_paths`, and matching `*_count` fields.
`chunk_reuse` includes `reused_chunks` and `new_chunks` when a publishable extension can be
previewed. Extension shard thresholds and share counts are bounded to `1..255` when enabled.

For `api inspect extend`, `resolved_policy`, `chunk_reuse`, and `estimated_extension_bytes` are
execution-grade preview values for the pending extension when unlock/auth requirements are satisfied
and the selected scope contains changes. Inspect also render-validates the pending artifacts in a
temporary no-publish workspace before reporting the extension as ready. `resolved_policy` is `null`
when runtime policy cannot be evaluated yet.

Compact results include the source `root_dir` or `source_scan`, the emitted standalone `output_dir`,
a fresh standalone `doc_id`, and a stable `artifacts` object for generated PDFs.

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
  `--input -`; `ethernity api compact` was invoked without `--root-dir` or `--scan`;
  `ethernity api extend` or `ethernity api inspect extend` was invoked without `--root-dir`
- `OUTPUT_REQUIRED`: `ethernity api recover` was invoked without `--output`, or
  `ethernity api compact` was invoked without `--output-dir`
- `CONFIG_INPUT_REQUIRED`: `ethernity api config set` was invoked without `--input-json`
- `CONFIG_JSON_INVALID`: the JSON patch passed to `api config set` was malformed, not a JSON
  object, or not valid UTF-8
- `CONFIG_UNKNOWN_FIELD`: the patch referenced an unsupported config or onboarding field
- `CONFIG_INVALID_VALUE`: the patch supplied a value with the wrong type or enum value
- `CONFIG_CONFLICT`: the patch supplied conflicting settings (for example mismatched shard counts)
- `SHARD_DIR_NOT_FOUND`: `--shard-dir` path does not exist
- `SHARD_DIR_INVALID`: `--shard-dir` path is not a directory
- `SHARD_DIR_EMPTY`: `--shard-dir` contains no `.txt` files
- `SIGNING_KEY_SHARD_DIR_NOT_FOUND`: `--signing-key-shard-dir` path does not exist
- `SIGNING_KEY_SHARD_DIR_INVALID`: `--signing-key-shard-dir` path is not a directory
- `SIGNING_KEY_SHARD_DIR_EMPTY`: `--signing-key-shard-dir` contains no `.txt` files
- `EXTENSION_INPUT_REQUIRED`: `ethernity api extend` was invoked without `--input`, `--input-dir`,
  or `--input -`; `ethernity api inspect extend` has no explicit selected scope
- `EXTENSION_INVALID_POLICY`: `ethernity api extend` received an unsupported or inconsistent shard /
  unlock-policy combination
- `EXTENSION_NO_CHANGES`: `ethernity api extend` found no changed or new paths in the selected
  scope; `api inspect extend` reports a no-op preview instead of raising this code
- `EXTENSION_MAIN_CARRIER_INVALID`: staged extension MAIN carriers failed ciphertext / AUTH validation
- `EXTENSION_SHARD_CARRIER_INVALID`: staged extension shard carriers failed payload validation
- `EXTENSION_TOO_LARGE`: the encrypted extension ciphertext exceeds the release size limit
- `EXTENSION_PUBLISH_TARGET_INVALID`: the extension publish target cannot be validated before
  writing
- `COMPACT_INVALID_POLICY`: `ethernity api compact` could not preserve the source or root shard
  policy
- `RECOVERY_HEAD_UNTRUSTED`: recover or compact could not authenticate or reconstruct the requested
  recovery head, or the latest supplied recovery head when no explicit head was requested

For `api extend`, every documented Stable Blocking Issue Code may also appear as command
`error.code` when a readiness blocker is promoted during publish-plan preparation. Those promoted
codes are part of the stable command error contract.

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

## Stable Blocking Issue Codes

Current inspect `blocking_issues[].code` values:

- `AUTH_PAYLOAD_MISSING`
- `AUTH_PAYLOAD_MULTIPLE`
- `AUTH_PAYLOAD_DOC_ID_MISMATCH`
- `AUTH_PAYLOAD_FRAME_INVALID`
- `AUTH_PAYLOAD_INVALID`
- `AUTH_DOC_HASH_MISMATCH`
- `AUTH_SIGNATURE_INVALID`
- `PASSPHRASE_SHARDS_UNDER_QUORUM`
- `PASSPHRASE_SHARDS_INVALID`
- `PASSPHRASE_INVALID`
- `PASSPHRASE_REQUIRED`
- `AUTH_REQUIRED`
- `UNLOCK_FAILED`
- `SIGNING_KEY_SHARDS_REQUIRED`
- `SIGNING_KEY_SHARDS_UNDER_QUORUM`
- `SIGNING_KEY_SHARDS_INVALID`
- `PASSPHRASE_REPLACEMENT_NOT_READY`
- `SIGNING_KEY_REPLACEMENT_NOT_READY`
- `ROOT_AUTHORITY_MISMATCH`
- `ROOT_SHARD_POLICY_INVALID`
- `EXTENSION_INPUT_REQUIRED`
- `RECOVERY_HEAD_UNTRUSTED`
- `EXTENSION_LAYOUT_INVALID`
- `EXTENSION_PUBLISH_TARGET_INVALID`
- `EXTENSION_INVALID_POLICY`
- `EXTENSION_NO_CHANGES`
- `EXTENSION_TOO_LARGE`
- `SEALED_ROOT_NOT_EXTENDABLE`
- `CHAIN_INVALID`
- `DELETE_NOT_SUPPORTED`

Additional blocking issue codes may be added in a backwards-compatible way. Existing documented
codes remain stable once listed here.

## Artifact Kinds

Current artifact kinds:

- Backup: `qr_document`, `recovery_document`, `recovery_kit_index`, `shard_document`,
  `signing_key_shard_document`, `layout_debug_json`
- Compact: `qr_document`, `recovery_document`, `recovery_kit_index`, `shard_document`,
  `signing_key_shard_document`, `layout_debug_json`
- Extend: `qr_document`, `recovery_document`, `recovery_kit_index`, `shard_document`,
  `signing_key_shard_document`, `layout_debug_json`
- Mint: `shard_document`, `signing_key_shard_document`, `layout_debug_json`
- Recover: `recovered_file`

Inspect commands never emit `artifact` events.

## Phase IDs

Stable phase ids currently emitted by the API:

- Backup: `plan`, `input`, `backup`, `prepare`, `encrypt`, `shard`, `render`
- Compact: `compact`
- Config: `load`, `validate`, `write`
- Extend: `plan`, `render`, `validate`, `publish`
- Extend inspect: `plan`
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

- `doc_id`, `selected_extension_index`, `selected_extension_doc_hash`,
  `expected_head_doc_hash`, `validated_head_index`, `validated_head_doc_hash`,
  `freshness_scope`, `input_label`, `input_detail`, `auth_status`
- `source_summary` when decryption is possible, otherwise `null`
- `frame_counts.main|auth|shard`
- `unlock.mode|passphrase_provided|validated_shard_count|required_shard_threshold|shard_share_count|satisfied`
- `blocking_issues` and `warnings`

When recovery input contains multiple MAIN documents, such as a root backup plus extension
documents, `api inspect recover` remains readiness-oriented. If the root cannot yet be selected
because unlock material is missing or wrong, it still emits a `result` event with
`source_summary: null`, aggregate frame counts, and an unlock/root-selection blocking issue.
When scanning a backup root directory, recovery imports extension carriers by content. Directory
names, filenames, and redundant carrier copies are not required for extension chain recovery.
Extension recovery documents are human-readable fallback artifacts and are not treated as
machine-readable extension carriers.

`ethernity api inspect mint` reports:

- `doc_id`, `selected_extension_index`, `selected_extension_doc_hash`,
  `expected_head_doc_hash`, `validated_head_index`, `validated_head_doc_hash`,
  `freshness_scope`, `input_label`, `input_detail`, `auth_status`
- `source_summary` when decryption is possible, otherwise `null`
- `frame_counts.main|auth|shard|signing_key_shard`
- `unlock.validated_passphrase_shard_count|required_passphrase_threshold|satisfied`
- `signing_key.validated_shard_count|required_threshold|satisfied|source`
- `mint_capabilities.can_mint_passphrase_shards|can_mint_signing_key_shards`
- `blocking_issues` and `warnings`

`ethernity api inspect extend` reports:

- `doc_id`, `input_label`, `input_detail`, `input_kind`
- `source_summary`, `frame_counts`, `root_doc_id`, `root_doc_hash`, `chain_id`
- `auth_status`, `discovered_extension_dirs`, `validated_head_index`, `validated_head_doc_hash`,
  `expected_head_doc_hash`, `freshness_scope`
- `unlock.mode|passphrase_provided|validated_shard_count|required_shard_threshold|shard_share_count|satisfied`
- `validated_head_auth_status`, `validated_head_root_authority_verified`
- `available_extensions`, `ancestry_valid`, `signing_authority`
- `selected_scope`, `diff_summary`, `resolved_policy`, `chunk_reuse`, `estimated_extension_bytes`
- `blocking_issues` and `warnings`

For mint inspect, `frame_counts.signing_key_shard` reports decoded signing-key shard input frames.
Signing-key readiness comes from `signing_key.satisfied`; `validated_shard_count` is informational
and can be `0` when the backup already embeds a signing seed.

For extend inspect, `unlock.satisfied` only describes root decryption readiness. Use
`blocking_issues`, `signing_authority.satisfied`, and the validated-head fields to decide whether
the write-producing extend action is ready. A selected scope with no changed or new paths reports
`EXTENSION_NO_CHANGES` as a blocking issue. A missing explicit scope reports
`EXTENSION_INPUT_REQUIRED` as a blocking issue.

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
- `extension.chunking.target_size`, `extension.chunking.min_size`,
  `extension.chunking.max_size`
- `defaults.backup.*`
- `defaults.recover.output`
- `defaults.extend.*`
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
- `source`: `user`, `default`, or `explicit`

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
    "extension": {"chunking": {"target_size": 16384, "min_size": 4096, "max_size": 65536}},
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
{"type":"started","schema_version":1,"command":"recover","args":{"config":null,"paper":null,"fallback_file":null,"payloads_file":"main_payloads.txt","scan":[],"has_passphrase":true,"shard_fallback_file":[],"shard_payloads_file":[],"shard_scan":[],"auth_fallback_file":null,"auth_payloads_file":null,"extension_index":null,"extension_doc_hash":null,"expected_head_doc_hash":null,"output":"/tmp/out/secret.txt","quiet":true,"debug":false}}
{"type":"phase","id":"plan","label":"Resolving recovery inputs"}
{"type":"progress","phase":"plan","current":1,"total":1,"unit":"step","details":{"main_frame_count":2,"auth_frame_count":1,"shard_frame_count":0}}
{"type":"phase","id":"decrypt","label":"Decrypting and inspecting payload"}
{"type":"artifact","kind":"recovered_file","path":"/tmp/out/secret.txt","details":{"manifest_path":"secret.txt","size":42}}
{"type":"result","ok":true,"command":"recover","output_path":"/tmp/out/secret.txt","output_path_kind":"file","doc_id":"0123456789abcdef","selected_extension_index":null,"selected_extension_doc_hash":null,"expected_head_doc_hash":null,"validated_head_index":0,"validated_head_doc_hash":"89abcdef0123456789abcdef0123456789abcdef0123456789abcdef01234567","freshness_scope":null,"auth_status":"verified","input_label":"QR payloads","input_detail":"main_payloads.txt","manifest":{"format_version":1,"input_origin":"file","input_roots":[],"sealed":true,"file_count":1,"payload_codec":"raw","payload_raw_len":null},"files":[{"manifest_path":"secret.txt","output_path":"/tmp/out/secret.txt","size":42,"sha256":"0123","mtime":0}]}
```

```json
{"type":"started","schema_version":1,"command":"recover","args":{"operation":"inspect","config":null,"paper":null,"fallback_file":null,"payloads_file":"main_payloads.txt","scan":[],"has_passphrase":true,"shard_fallback_file":[],"shard_payloads_file":[],"shard_scan":[],"auth_fallback_file":null,"auth_payloads_file":null,"extension_index":null,"extension_doc_hash":null,"expected_head_doc_hash":null,"quiet":true,"debug":false}}
{"type":"phase","id":"plan","label":"Resolving recovery inputs"}
{"type":"progress","phase":"plan","current":1,"total":1,"unit":"step","details":{"main_frame_count":2,"auth_frame_count":1,"shard_frame_count":0}}
{"type":"phase","id":"decrypt","label":"Decrypting and inspecting payload"}
{"type":"progress","phase":"decrypt","current":1,"total":1,"unit":"step","details":{"file_count":1,"manifest_file_count":1}}
{"type":"result","ok":true,"command":"recover","operation":"inspect","doc_id":"0123456789abcdef","selected_extension_index":null,"selected_extension_doc_hash":null,"expected_head_doc_hash":null,"validated_head_index":0,"validated_head_doc_hash":"89abcdef0123456789abcdef0123456789abcdef0123456789abcdef01234567","freshness_scope":null,"auth_status":"verified","input_label":"QR payloads","input_detail":"main_payloads.txt","source_summary":{"format_version":1,"input_origin":"file","input_roots":[],"sealed":true,"file_count":1,"payload_codec":"raw","payload_raw_len":null},"frame_counts":{"main":2,"auth":1,"shard":0},"unlock":{"mode":"passphrase","passphrase_provided":true,"validated_shard_count":0,"required_shard_threshold":null,"shard_share_count":null,"satisfied":true},"blocking_issues":[],"warnings":[]}
```

```json
{"type":"started","schema_version":1,"command":"compact","args":{"config":null,"paper":null,"design":null,"root_dir":null,"scan":["root.pdf","extension-01.pdf"],"output_dir":"compacted","shard_fallback_file":[],"shard_payloads_file":[],"shard_scan":[],"auth_fallback_file":null,"auth_payloads_file":null,"expected_head_doc_hash":null,"allow_stale_head":true,"layout_debug_dir":null,"qr_chunk_size":null,"has_passphrase":true,"quiet":true,"debug":false}}
{"type":"phase","id":"compact","label":"Replaying source chain and preparing checkpoint"}
{"type":"progress","phase":"compact","current":0,"total":1,"unit":"step","details":{"root_dir":null,"scan":["root.pdf","extension-01.pdf"],"output_dir":"compacted"}}
{"type":"progress","phase":"compact","current":1,"total":1,"unit":"step","details":{"root_dir":null,"scan":["root.pdf","extension-01.pdf"],"output_dir":"compacted"}}
{"type":"artifact","kind":"qr_document","path":"compacted/qr_document.pdf","details":{"filename":"qr_document.pdf","size":1234}}
{"type":"artifact","kind":"recovery_document","path":"compacted/recovery_document.pdf","details":{"filename":"recovery_document.pdf","size":2345}}
{"type":"result","ok":true,"command":"compact","doc_id":"0123456789abcdef","root_dir":null,"source_scan":["root.pdf","extension-01.pdf"],"output_dir":"compacted","artifacts":{"qr_document":"compacted/qr_document.pdf","recovery_document":"compacted/recovery_document.pdf","recovery_kit_index":null,"shard_documents":[],"signing_key_shard_documents":[]},"expected_head_doc_hash":null,"validated_head_index":1,"validated_head_doc_hash":"89abcdef0123456789abcdef0123456789abcdef0123456789abcdef01234567","freshness_scope":"supplied_carriers_only"}
```

```json
{"type":"started","schema_version":1,"command":"config","args":{"operation":"get","config":null,"input_json":null}}
{"type":"phase","id":"load","label":"Loading config"}
{"type":"result","ok":true,"command":"config","operation":"get","path":"/home/user/.config/ethernity/config.toml","source":"user","status":"valid","errors":[],"values":{"templates":{"default_name":"sentinel","template_name":null,"recovery_template_name":null,"shard_template_name":null,"signing_key_shard_template_name":null,"kit_template_name":null},"page":{"size":"A4"},"qr":{"error":"M","chunk_size":512},"extension":{"chunking":{"target_size":16384,"min_size":4096,"max_size":65536}},"defaults":{"backup":{"base_dir":null,"output_dir":null,"shard_threshold":null,"shard_count":null,"signing_key_mode":null,"signing_key_shard_threshold":null,"signing_key_shard_count":null,"payload_codec":"auto","qr_payload_codec":"raw"},"recover":{"output":null},"extend":{"base_dir":null,"unlock_policy":null,"shard_threshold":null,"shard_count":null,"signing_key_mode":null,"signing_key_shard_threshold":null,"signing_key_shard_count":null,"qr_payload_codec":"raw"}},"ui":{"quiet":false,"no_color":false,"no_animations":false},"debug":{"max_bytes":1024},"runtime":{"render_jobs":"auto"}},"options":{"template_designs":["archive","forge","ledger","maritime","sentinel"],"page_sizes":["A4","LETTER"],"qr_error_correction":["L","M","Q","H"],"payload_codecs":["auto","raw","gzip"],"qr_payload_codecs":["raw","base64"],"signing_key_modes":["embedded","sharded"],"extension_unlock_policies":["self-contained","reuse-root"],"extension_signing_key_modes":["not-stored","sharded"],"onboarding_fields":["template_design","page_size","backup_output_dir","qr_chunk_size","qr_error_correction","sharding","payload_codec","qr_payload_codec"]},"onboarding":{"needed":true,"configured_fields":[],"available_fields":["template_design","page_size","backup_output_dir","qr_chunk_size","qr_error_correction","sharding","payload_codec","qr_payload_codec"]}}
```

Recover can also scan QR payloads directly from PDFs, images, or directories by using `--scan`:

```bash
ethernity api recover --scan "/path/to/qr_document.pdf" --passphrase "correct horse battery staple" --output "/tmp/recovered.bin"
```

`--scan` may be combined with either `--payloads-file` or `--fallback-file` when a recovery set
spans QR-readable artifacts and typed/transcribed text. `--fallback-file` and `--payloads-file`
remain mutually exclusive with each other.

Passphrase shard PDFs/images can be scanned separately with `--shard-scan`:

```bash
ethernity api recover --scan "/path/to/qr_document.pdf" --shard-scan "/path/to/shard-01.pdf" --shard-scan "/path/to/shard-02.pdf" --output "/tmp/recovered.bin"
```

For extended backup roots, `--extension-index <n>` selects a specific authenticated replay target.
Use `--extension-index 0` for intentional root-only recovery when the supplied extension head is not
trusted or the UI needs the original backup state. Recursive backup-root scans ignore published
extension carriers after an explicitly selected numeric index, so rollback to an earlier index is not
blocked by later carrier damage.
Use `--expected-head-doc-hash <hash>` with `recover`, `inspect recover`, `extend`, `inspect extend`,
or `compact` when the client already knows the trusted head. Commands fail closed if the validated
supplied head does not match. `freshness_scope: "supplied_carriers_only"` means the validated head is
the freshest authenticated head among the supplied carriers, not proof that no later carrier exists
elsewhere.

## Client Guidance

- Parse events line-by-line as they arrive
- Ignore unknown fields for forward compatibility
- Handle unknown event codes as non-fatal unless the event type is `error`
- Treat artifact events as success-only notifications; a failed command may still have written files
- Use artifact paths rather than assuming output filenames
- Use `output_path_kind` to distinguish file outputs from directory outputs
- Treat inspect `blocking_issues` as readiness guidance, not command failure
- Use `api config get/set` for GUI settings management and onboarding state
- Expect `api backup` / `api compact` / `api extend` / `api mint` / `api recover` to use the existing user config when present
- Expect `api inspect recover` / `api inspect mint` to avoid file writes and artifact events
- Expect `api inspect extend` to avoid persistent user-output writes and artifact events; successful
  extension readiness previews render into a temporary workspace that is cleaned up before the
  command returns
- Prefer `code` values for logic and `message` values for display
- Treat stdin as opt-in for `api recover`; pass `--fallback-file -` for typed fallback text or `--payloads-file -` for QR payload lines
- Do not extract fallback text from PDF or image files; PDF/image recovery inputs are QR scan inputs only
`extend` also accepts `--unlock-policy self-contained|reuse-root`.
`reuse-root` disables extension-local passphrase shard emission and rejects explicit extension
passphrase shard overrides for the new extension. It requires a recoverable root passphrase shard
quorum, either from the shard set supplied to unlock the root backup or from authenticated
root-level shard documents discovered in the backup root. Operators then unlock the extension
through that root shard set. Signing authority recovery remains independent: `reuse-root` emits no
extension-local signing-key shards by default, but explicit `--signing-key-mode sharded` or
signing-key shard-count options request root/chain signing authority shard documents for future
extension minting.
If no root or extension shard policy is available, `api extend` fails closed instead of emitting a
plaintext passphrase recovery document by default; pass `--shard-count 0` only when plaintext
passphrase output is intentional.

`api extend` and `api inspect extend` can also take repeatable `--scan` inputs containing the
root backup and extension QR-document PDFs/images. In scan mode, `--root-dir` is the writable
publish target for the next extension, not the source of truth for the existing chain; it may be a
fresh missing directory when its parent is writable, or an existing empty directory. To avoid mixing
scanned source material with a stale digital layout, scan-mode publishing writes a loose
`extension-<index>-<doc_id>` bundle directly under that target and does not create canonical
`extensions/<index>` output. Inspect/result payloads can report `input_kind: "scanned_chain"`, and
started events include the `scan` array in schema version 1.

Because scan-mode extend can only authenticate the supplied carriers, it cannot prove that no later
extension exists elsewhere. Provide `--expected-head-doc-hash <hash>` to pin the trusted latest
head. If no trusted marker exists and the operator explicitly accepts the stale-head risk, pass
`--allow-stale-head`; otherwise inspect reports `RECOVERY_HEAD_UNTRUSTED` and `api extend` fails
closed before publishing.

`api extend` and `api inspect extend` can unlock the selected backup with passphrase shard inputs
by using `--shard-fallback-file`, `--shard-payloads-file`, or `--shard-scan`.
When those shard inputs appear to target published extension state but cannot be matched to the
current root chain, inspect reports `PASSPHRASE_SHARDS_INVALID` with
`details.stage: "extension_shard_unlock"` instead of treating the shard inputs as absent.
Both commands require `--root-dir`; without `--scan`, the inspect form stays read-only and targets
an existing non-symlink backup root directory.
Both commands also accept `--input -` for stdin-backed file content when selecting an explicit
scope.
`api inspect extend` accepts the same extension-policy preview knobs as `api extend`:
`--qr-chunk-size`, `--layout-debug-dir`, `--unlock-policy`, `--shard-threshold`,
`--shard-count`, `--signing-key-mode not-stored|sharded`, `--signing-key-shard-threshold`, and
`--signing-key-shard-count`. The inspect form validates `--layout-debug-dir`, preflights the
extension publish target, and render-validates pending artifacts in a temporary no-publish
workspace without creating persistent files under the publish target.
When the active design provides a compatible `recovery_kit_index` template, `api extend` emits an
extension-local recovery kit index. The index records the required root backup documents as external
dependencies because extension recovery is not self-contained. `api inspect extend` does not emit
artifact paths, but its readiness preview reflects the same policy by estimating the extension
payload and surfacing blocking issues when runtime preparation would fail. Designs without a
compatible template omit that optional index document.

If `api extend` encounters an inspect-time blocking issue while preparing the publish plan, it emits
that stable `blocking_issues[].code` as the command `error.code`. Clients should therefore handle
documented blocking issue codes on `api extend` error events as well as inspect result events.

For `api inspect extend`, result events also surface authenticated-head status:

- `validated_head_auth_status`
- `validated_head_root_authority_verified`

For a root-only head, `validated_head_root_authority_verified` is `true` only when the root AUTH
status is `verified` and the root-derived signing authority is present. Clients should pair this
field with `validated_head_auth_status` and `blocking_issues` before treating a head as trusted.

Recovery-valid and append-valid are intentionally different. `api recover` may restore content from
the available authenticated machine-readable carriers, including a degraded extension directory
whose redundant `recovery_document-*` PDF is missing. `api extend` and `api inspect extend` require
the published head to remain append-valid before creating another extension, so a degraded directory
can still produce a blocking issue such as `EXTENSION_LAYOUT_INVALID` or
`RECOVERY_HEAD_UNTRUSTED`. Append-valid inspection validates the required `recovery_document-*` PDF
as a human fallback artifact by checking that its visible AUTH and MAIN fallback sections bind to
the QR-derived extension identity; the PDF is still not used as a machine replay source.

`available_extensions` entries always include the numeric `index` alongside `dir_name`, `doc_id`,
and non-null `doc_hash`. Directories whose payloads cannot be fully decoded are reported through
blocking issues instead of partial `available_extensions` entries. When chain authentication has
been evaluated, entries may also include:

- `auth_status`
- `root_authority_verified`
