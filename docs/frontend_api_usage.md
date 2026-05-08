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
- reuse saved backup/config defaults when the UI does not override them explicitly

For `api inspect extend`, use these final `result` fields for chain-head state:

- `validated_head_index`: the latest extension index that was reconstructed and authenticated, or
  `0` for the root backup, or `null` when no trusted head is available
- `validated_head_doc_hash`: the authenticated hash for that validated head, or `null`
- `validated_head_auth_status`: auth status for the validated head when known
- `validated_head_root_authority_verified`: whether the validated head is signed by the root
  authority when known
- `available_extensions`: discovered extension entries; entries may include `auth_status` and
  `root_authority_verified` after chain authentication has been evaluated
- `ancestry_valid`: whether the inspected chain ancestry is valid when the backend can determine it

If `blocking_issues` contains `RECOVERY_HEAD_UNTRUSTED`, show the extension chain as not ready for
write-producing actions. The `details` object identifies the failed/latest/requested head and the
last validated head. Do not treat filenames or `available_extensions` alone as authenticated proof of
the current chain state; use the validated-head fields for that.

### Compaction Flow

Use `ethernity api compact` when the UI needs to flatten the latest validated chain state into a
fresh standalone backup.

The command:

- requires `--root-dir` and `--output-dir`
- reuses saved backup/config defaults for render policy when the UI does not override them
- performs authenticated recovery semantics, not rescue-mode recovery

### Recovery Flow

Use `ethernity api inspect recover` first when the UI needs readiness data without writing files:

- validate shard quorum before enabling recovery
- validate AUTH presence or report `auth_status`
- inspect `source_summary`, `frame_counts`, `unlock`, `blocking_issues`, and `warnings`

Use `ethernity api recover` for the actual extraction step.

Both commands accept the same recovery input flags in one of these ways:

- `--scan <pdf-or-image-or-dir>` for QR scanning from recovery PDFs, image files, or folders
- `--shard-scan <pdf-or-image-or-dir>` for QR scanning from passphrase shard PDFs, image files, or folders
- `--payloads-file <file>` for pre-extracted QR payloads
- `--fallback-file <file>` for fallback text
- `--shard-dir <dir>` for a directory of passphrase shard recovery text files
- `--extension-index <n>` or `--extension-doc-hash <hash>` when the UI needs a specific extension replay target
- `--rescue-mode` when the operator deliberately chooses best-effort recovery without normal authentication verification
- optional shard/auth inputs when the UI has them

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
  --scan "/path/to/recovery_document.pdf" \
  --shard-scan "/path/to/shard-01.pdf" \
  --shard-scan "/path/to/shard-02.pdf"
```

## Recovery From PDFs

### Single Recovery PDF

```bash
uv run python -m ethernity.cli api recover \
  --scan "/path/to/recovery_document.pdf" \
  --passphrase "correct horse battery staple" \
  --output "/tmp/recovered.bin"
```

### Multiple Scan Inputs

```bash
uv run python -m ethernity.cli api recover \
  --scan "/path/to/recovery_document.pdf" \
  --scan "/path/to/phone-photos/" \
  --passphrase "correct horse battery staple" \
  --output "/tmp/recovered.bin"
```

### Recovery PDF Plus AUTH Payload File

```bash
uv run python -m ethernity.cli api recover \
  --scan "/path/to/recovery_document.pdf" \
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
  --scan "/path/to/recovery_document.pdf" \
  --shard-payloads-file "/path/to/passphrase_shards.txt" \
  --signing-key-shard-payloads-file "/path/to/signing_key_shards.txt"
```

Use the final `result.blocking_issues`, `result.unlock`, `result.signing_key`, and
`result.mint_capabilities` fields to decide whether the UI should offer minting yet.
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
