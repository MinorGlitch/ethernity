# Frontend API Usage Plan

This document gives the frontend team a practical plan for integrating the machine-readable
`ethernity api` surface.

## Goals

- Build onboarding and settings in the GUI, not in CLI prompts.
- Use NDJSON from `ethernity api` as the only process protocol.
- Support recovery from PDFs, images, text payload files, and mixed inputs.
- Keep all long-running work off the UI thread and stream progress live.

## Transport Rules

- Run `ethernity api ...` as a subprocess.
- Treat `stdout` as NDJSON only.
- Read one JSON object per line as it arrives.
- Treat `stderr` as debug/troubleshooting only.
- Consider the command successful only when the final event is `{"type":"result","ok":true,...}`.

## Commands To Use

- Settings + onboarding state: `ethernity api config get`
- Save settings + onboarding completion: `ethernity api config set`
- Create backup artifacts: `ethernity api backup`
- Inspect extension readiness from a backup root: `ethernity api inspect extend`
- Create extension artifacts inside a backup root: `ethernity api extend`
- Compact a backup root into a fresh standalone backup: `ethernity api compact`
- Inspect recovery readiness from PDFs/images/text inputs: `ethernity api inspect recover`
- Recover files from PDFs/images/text inputs: `ethernity api recover`
- Inspect mint readiness from an existing backup: `ethernity api inspect mint`
- Mint new shard PDFs from an existing backup: `ethernity api mint`

## Recommended Frontend Flows

### App Startup

1. Run `ethernity api config get`.
2. Read the final `result.status`, `result.errors`, `result.values`, `result.options`, and
   `result.onboarding` payloads.
3. If `result.status` is not `valid`, show repair UX using `result.values` plus the reported
   `result.errors`.
4. If `result.onboarding.needed` is `true`, show the GUI onboarding flow.
5. Otherwise, load the normal settings screen using `result.values`.

### GUI Onboarding

1. Call `ethernity api config get`.
2. Build the onboarding UI from:
   - `result.values` for current defaults
   - `result.options` for allowed choices
   - `result.onboarding.available_fields` for marker field ids
   - `result.errors` if the current config needs repair
3. When the user finishes, send a partial patch with `ethernity api config set --input-json ...`.
4. Include:
   - the values the user chose
   - `onboarding.mark_complete = true`
   - `onboarding.configured_fields = [...]` for the fields the GUI collected

### Settings Screen

1. Load current settings with `ethernity api config get`.
2. Save only changed fields with `ethernity api config set`.
3. Do not send onboarding metadata from the normal settings UI unless the screen is intentionally
   completing or resetting onboarding.

`api config get` is read-only: when the default user config does not exist yet, it reports the
packaged default config path and default values without creating a user config file.

### Backup Flow

1. Let the user choose input files/directories and output destination.
2. Pass explicit values for anything the UI is controlling directly.
3. Otherwise rely on saved config defaults.
4. Stream `phase`, `progress`, `warning`, `artifact`, and `result` into the UI.
5. Use the final `result.artifacts` object as the source of truth for generated files.

Backup output rule for the GUI:

- if `api backup --output-dir` points to an existing directory, Ethernity treats it as a parent
  directory and creates `backup-<doc_id>` inside it
- if the path does not exist, Ethernity creates that exact directory and writes the backup there

Mint output rule for the GUI:

- if `api mint --output-dir` points to an existing directory, Ethernity treats it as a parent
  directory and creates `mint-<doc_id>` inside it
- if the path does not exist, Ethernity creates that exact directory and writes the minted shards there

Mint preflight rule for the GUI:

- use `api inspect mint` before asking for an output directory when the UI only needs readiness,
  shard quorum, signing-key status, or mint capability metadata
- use `api mint` only for the write-producing step after the user confirms generation

### Extension Flow

Use `ethernity api inspect extend` first when the UI needs readiness, unlock status, diff
summary, or extension policy preview without writing files.

Use `ethernity api extend` for the write-producing step after the user confirms the selected
scope and output policy.

Both commands:

- require `--root-dir`
- can unlock with `--passphrase`, `--shard-fallback-file`, `--shard-payloads-file`, or `--shard-scan`
- accept explicit scope selection through `--input`, `--input-dir`, and `--base-dir`
- accept preview/render knobs through `--qr-chunk-size` and `--layout-debug-dir`
- use `--unlock-policy self-contained|reuse-root`, `--shard-threshold`, and `--shard-count` for
  extension passphrase recovery policy
- use `--signing-key-mode not-stored|sharded`, `--signing-key-shard-threshold`, and
  `--signing-key-shard-count` for extension-local signing-key recovery
- reuse saved backup/config defaults when the UI does not override them explicitly

If the UI runs `api inspect extend` before a scope is selected, treat
`EXTENSION_INPUT_REQUIRED` in `blocking_issues` as the normal not-ready state.
If supplied extension-local shard inputs are stale or from another chain, inspect reports
`PASSPHRASE_SHARDS_INVALID` with `details.stage == "extension_shard_unlock"`; keep the write action
disabled until the user supplies matching shards or a passphrase.
When a selected scope is present, inspect also preflights the publish target without writing; treat
`EXTENSION_PUBLISH_TARGET_INVALID` as a not-ready state for write-producing actions.

For `api inspect extend`, use these final `result` fields for chain-head state:

- `validated_head_index`: the latest supplied extension index that was reconstructed and
  authenticated, or `0` for the root backup, or `null` when no trusted head is available
- `validated_head_doc_hash`: the authenticated hash for that validated head, or `null`
- `validated_head_auth_status`: auth status for the validated head when known
- `validated_head_root_authority_verified`: whether the validated head is signed by the root
  authority when known
- `available_extensions`: discovered extension entries with explicit `index`, `dir_name`, `doc_id`,
  and `doc_hash`; entries may include `auth_status` and `root_authority_verified` after chain
  authentication has been evaluated
- `ancestry_valid`: whether the inspected chain ancestry is valid when the backend can determine it
- `resolved_policy`: the execution-grade passphrase/signing-key/output preview when the selected
  scope can be prepared, otherwise `null`

If `blocking_issues` contains `RECOVERY_HEAD_UNTRUSTED`, show the extension chain as not ready for
write-producing actions. The `details` object identifies the failed/latest/requested head and the
last validated head. Do not treat filenames or `available_extensions` alone as authenticated proof of
the supplied chain state; use the validated-head fields for that. These fields do not prove that no
later extension exists outside the supplied recovery set.

### Compaction Flow

Use `ethernity api compact` when the UI needs to flatten the latest supplied validated chain state
into a fresh standalone backup.

The command:

- requires `--root-dir` and `--output-dir`
- reuses saved backup/config defaults for render policy when the UI does not override them, but
  never infers the output directory from saved backup defaults
- performs authenticated recovery semantics

### Recovery Flow

Use `ethernity api inspect recover` first when the UI needs readiness data without writing files:

- validate shard quorum before enabling recovery
- validate AUTH presence or report `auth_status`
- inspect `source_summary`, `frame_counts`, `unlock`, `blocking_issues`, and `warnings`
- expect mixed root-plus-extension inputs to return a normal inspect `result` with
  `source_summary: null` until passphrase or shard material can select the root document

Use `ethernity api recover` for the actual extraction step.

Both commands accept the same recovery input flags in one of these ways:

- `--scan <pdf-or-image-or-dir>` for QR scanning from QR-document PDFs, image files, or folders
- `--shard-scan <pdf-or-image-or-dir>` for QR scanning from passphrase shard PDFs, image files, or folders
- `--payloads-file <file>` for pre-extracted QR payloads
- `--fallback-file <file>` for fallback text
- `--shard-dir <dir>` for a directory of passphrase shard recovery text files
- `--extension-index <n>` or `--extension-doc-hash <hash>` when the UI needs a specific extension replay target
- `--extension-index 0` for intentional root-only recovery
- optional shard/auth inputs when the UI has them

A scan input may be combined with either `--payloads-file` or `--fallback-file` when the user has
a mix of QR-readable artifacts and typed/transcribed recovery text. `--fallback-file` and
`--payloads-file` are still mutually exclusive with each other.

Extension `recovery_document-*` PDFs are human-readable fallback artifacts, not machine-readable
scan inputs. Use extension `qr_document-*` artifacts for `--scan`. If QR recovery is unavailable,
users may manually type or transcribe fallback text into `--fallback-file`; do not extract fallback
text from PDF or image files.

Important:

- `api inspect recover` is read-only and does not require `--output`
- `api inspect recover` does not emit `artifact` events
- `api recover` requires explicit `--output`
- if `--output` points to an existing directory, a single recovered file is written inside that
  directory using its manifest filename
- `stdout` stays reserved for NDJSON, so recovered content is always written to disk

### Recovery Preflight Example

```bash
uv run python -m ethernity.cli api inspect recover \
  --scan "/path/to/qr_document.pdf" \
  --shard-scan "/path/to/shard-01.pdf" \
  --shard-scan "/path/to/shard-02.pdf"
```

## Recovery From PDFs

### Single Recovery PDF

```bash
uv run python -m ethernity.cli api recover \
  --scan "/path/to/qr_document.pdf" \
  --passphrase "correct horse battery staple" \
  --output "/tmp/recovered.bin"
```

### Multiple Scan Inputs

```bash
uv run python -m ethernity.cli api recover \
  --scan "/path/to/qr_document.pdf" \
  --scan "/path/to/phone-photos/" \
  --passphrase "correct horse battery staple" \
  --output "/tmp/recovered.bin"
```

### Recovery PDF Plus AUTH Payload File

```bash
uv run python -m ethernity.cli api recover \
  --scan "/path/to/qr_document.pdf" \
  --auth-payloads-file "/path/to/auth_payloads.txt" \
  --passphrase "correct horse battery staple" \
  --output "/tmp/recovered.bin"
```

### Recovery PDF With Passphrase Shard Inputs

```bash
uv run python -m ethernity.cli api recover \
  --scan "/path/to/qr_document.pdf" \
  --shard-scan "/path/to/shard-01.pdf" \
  --shard-scan "/path/to/shard-02.pdf" \
  --output "/tmp/recovered.bin"
```

### Mint Preflight Example

```bash
uv run python -m ethernity.cli api inspect mint \
  --scan "/path/to/qr_document.pdf" \
  --shard-payloads-file "/path/to/passphrase_shards.txt" \
  --signing-key-shard-payloads-file "/path/to/signing_key_shards.txt"
```

Use the final `result.blocking_issues`, `result.unlock`, `result.signing_key`, and
`result.mint_capabilities` fields to decide whether the UI should offer minting yet.
When scan/import input includes extension carriers, `result.doc_id`,
`result.selected_extension_index`, `result.selected_extension_doc_hash`, and
`result.source_summary` describe the authenticated extension replay target, not just the root
backup.
Treat the two `mint_capabilities` flags independently; they reflect both readiness and the output
types currently enabled for this request, so one shard type can be ready while the other is
blocked or disabled.

Mint also accepts directory and scan variants for existing passphrase and signing-key shard inputs:
`--shard-dir`, `--shard-scan`, `--signing-key-shard-dir`, and `--signing-key-shard-scan`.
For replacement workflows, pass `--passphrase-replacement-count` and
`--signing-key-replacement-count` only after inspection shows compatible existing shard material.
Use `--passphrase-shards/--no-passphrase-shards` and
`--signing-key-shards/--no-signing-key-shards` to keep the two output families independent.

## Config Patch Shape

Write config changes through a JSON patch file or stdin.

Example onboarding/settings patch:

```json
{
  "values": {
    "templates": {
      "default_name": "forge"
    },
    "page": {
      "size": "LETTER"
    },
    "defaults": {
      "backup": {
        "output_dir": "/tmp/backups",
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
      "sharding"
    ]
  }
}
```

Example command:

```bash
uv run python -m ethernity.cli api config set --input-json "/path/to/config_patch.json"
```

## UI Mapping Recommendations

- `started`: create the operation row / task entry
- `phase`: update the current step label
- `progress`: update progress text and counters
- `warning`: show non-blocking inline warnings
- `artifact`: append generated files to the output panel for write-producing commands only
- `result`: finalize success state and enable open/reveal actions, or update readiness state for
  inspect commands
- `error`: finalize failure state and show the stable `code`

## Error Handling

- Use `error.code` for UI logic.
- Use `error.message` for human display.
- Keep a fallback UI path for unknown future codes.
- For config writes, treat failures as no-save and re-fetch with `api config get` if the UI needs a
  fresh snapshot.
- `RECOVERY_HEAD_UNTRUSTED` can appear either as an inspect `blocking_issues[].code` or as an
  `error.code` from write-producing recovery/extension/compaction commands. In both cases, ask the
  user to repair or select an earlier trusted head before continuing.
- The recovery API does not expose an unsigned recovery flag. If extension replay fails with
  `RECOVERY_HEAD_UNTRUSTED`, offer root-only recovery (`--extension-index 0`) or authenticated
  extension inputs.

## Frontend Checklist

- Use a streaming line reader for NDJSON.
- Do not parse partial lines.
- Always wait for the terminal `result` or `error` event.
- Keep a command-specific parser for `result.command` and `result.operation`.
- Use `result.options` from `api config get` to populate selects.
- Prefer explicit flags over relying on defaults when the UI is intentionally setting a value.
- Use `--scan` for PDF recovery support.
- Do not wait for `artifact` events from `api inspect recover` or `api inspect mint`.

## Suggested Rollout Order

1. Integrate `api config get` for app startup.
2. Build GUI onboarding on top of `api config set`.
3. Add backup flow.
4. Add recovery preflight with `api inspect recover`.
5. Add recovery execution from PDF with `api recover --scan ... --output ...`.
6. Add advanced recovery inputs for auth/shards.
7. Add mint preflight with `api inspect mint`.
8. Add mint execution flow.
9. Add extension preflight with `api inspect extend`.
10. Add extension execution with `api extend`.
11. Add compact execution with explicit `--output-dir`.
12. Surface root-plus-extensions as the normal ongoing backup lifecycle, not an advanced mode.
