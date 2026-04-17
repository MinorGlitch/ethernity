# Chunked Backup Extension Plan

This document captures the agreed implementation plan for extending existing backups through
authenticated, append-only extensions with content-defined chunking.

This is a planning document, not a normative specification. When implementation begins, any change
that affects wire format, recovery semantics, or interoperability must update `docs/format.md`,
`docs/format_notes.md`, and `docs/format_changes.md` in the same change set.

The extension feature is now implemented. This document remains historical planning context only;
live behavior is defined by `docs/format.md`, `docs/cli_api.md`, `docs/cli_api.schema.json`, and
the implementation/tests in the repository.

## Goals

- Add `extend` so users can append changes to an existing backup without recreating it from scratch.
- Keep the original standalone backup untouched and fully recoverable.
- Use content-defined chunking plus chain-local deduplication to avoid storing whole-file payloads
  again on every update.
- Provide a first-class compaction path when a delta chain approaches the current transport limit.
- Preserve the current artifact model where persisted outputs are printable or directly used for
  recovery.
- Keep recovery defaulting to the latest state, with optional extension selection.

## Non-Goals

- No in-place mutation of existing backup artifacts.
- No unsigned extension mode.
- No delete support in v1.
- No rename tracking in v1.
- No passphrase rotation in v1.
- No signing-authority rotation in v1.
- No new persisted machine-only sidecar artifacts in v1.
- No snapshot extension envelope type in v1.
- No in-place compaction or rewriting of existing root/extension artifacts in v1.
- No extension import from another backup in v1.

## Product Invariants

- `backup` remains unchanged and continues to create standalone backups.
- Existing unsealed standalone backups can be extended in place without duplication.
- The root standalone backup remains the immutable base state.
- The root backup passphrase remains the chain-wide decryption secret in v1.
- Sealed standalone backups remain recoverable, but they are terminal for `extend` in v1.
- Persisted extension outputs keep the current full backup artifact set.
- The encrypted MAIN payload remains the authoritative digital content for each generation.
- Trust decisions are bound to recovered MAIN ciphertext through derived `doc_hash` / `doc_id` and
  validated AUTH / shard payloads, consistent with the current format.
- Extension lineage metadata inside `Envelope V2` is trusted only after the extension MAIN
  ciphertext and its associated authenticated materials have been validated.
- Recovery and extension validation must work without any persisted sidecars such as `chain.json`.

## User Model

- An unsealed standalone backup can become extendable in place.
- A sealed standalone backup is terminal in v1: it can be recovered or compacted, but not extended.
- The root backup remains at the top level and is treated as the conceptual base state with index `0`.
- Appended extensions are written under an `extensions/` directory.
- Extension directories are sequential canonical decimal names with a minimum width of `2` digits:
  - `extensions/01/`
  - `extensions/02/`
  - `extensions/03/`
  - `extensions/99/`
  - `extensions/100/`
- Canonical directory rendering is `index` in base-10, left-padded with `0` only until width `2`.
- No gaps are allowed.
- Files inside each extension directory are named for operator clarity as
  `<doctype>-<N>-<docid>...`, where `N` is the directory number and `docid` is the derived
  ciphertext document id.
- Directory numbers and filename `N` values are operational hints only; the authoritative extension
  generation comes from decrypted `Envelope V2` metadata.
- Users explicitly select new-content scope through `--input`, `--input-dir`, and `--base-dir`.
- Recovery restores the latest state by default.
- Recovery can optionally target an extension by `index` or `doc_hash`.

## Persisted Artifact Model

The root backup keeps the existing standalone artifact set. Every persisted extension also emits the
same full backup artifact set:

- `qr_document-<N>-<docid>.pdf`
- `recovery_document-<N>-<docid>.pdf`
- `recovery_kit_index-<N>-<docid>.pdf` when supported by the active design
- passphrase shard PDFs using the same `<N>-<docid>` basename anchor when applicable
- signing-key shard PDFs using the same `<N>-<docid>` basename anchor when applicable for unsealed
  chains that opt into signing-key sharding

No new persisted sidecars are introduced in v1:

- no `chain.json`
- no persisted diff cache
- no persisted extension summary file
- no persisted chunk index outside encrypted extension payloads

The encrypted MAIN payload embedded in the printable artifacts remains the authoritative digital
content. It does not introduce a new persisted artifact class.

### Render and Output Policy

- `extend` and `compact` resolve `config`, `paper`, `design`, `qr_chunk_size`, and
  `layout_debug_dir` through the same surface as `backup`.
- Explicit CLI or API overrides apply only to the newly rendered extension or compacted output.
- Extension generations are not required to reuse the root generation's visual design.
- Extension directory validity is evaluated against the chosen render policy of that generation,
  not by requiring visual parity with the root artifact set.
- `recovery_kit_index-<N>-<docid>.pdf` is required only when the chosen design for that generation
  supports it.

### MAIN Recovery Source of Truth

- `qr_document-<N>-<docid>.pdf` remains a first-class MAIN recovery carrier.
- `recovery_document-<N>-<docid>.pdf` remains a first-class MAIN recovery carrier.
- Both must independently carry enough data to recover the extension MAIN ciphertext.
- `qr_document-<N>-<docid>.pdf` remains the dense QR-oriented representation.
- `recovery_document-<N>-<docid>.pdf` remains the fallback-oriented representation.
- Neither document is downgraded to metadata-only status for extensions.

## High-Level Architecture

- Standalone root backups keep the current `Envelope V1` model.
- Appended extensions use a new `Envelope V2` model.
- The root backup is not rewritten.
- Each extension is its own encrypted MAIN document with its own `doc_hash` and `doc_id`.
- AUTH and shard transport stay aligned with the current model.
- Recovery supports:
  - root standalone `Envelope V1`
  - appended extension `Envelope V2`

## Why Envelope V2

The current envelope semantics are tightly coupled to:

- a manifest that describes files
- payload bytes interpreted as concatenated file contents

Extension payloads need a different model:

- extension metadata
- file recipe replacements for changed paths only
- newly introduced chunk records

That is not a small extension of the current envelope semantics. A dedicated `Envelope V2` keeps the
boundary fail-closed and easier to reason about.

## Envelope V2 Overview

Each extension MAIN ciphertext decrypts to `Envelope V2`.

Suggested binary layout:

```text
MAGIC
VERSION = 2
HEADER_LEN
HEADER_CBOR
BODY_LEN
BODY_CBOR
```

Both header and body use canonical CBOR with compact positional structures where possible.

### Header Field Keys

Use integer keys in `HEADER_CBOR`:

- `1`: `version`
- `2`: `index`
- `4`: `parent_doc_hash`
- `5`: `root_doc_hash`
- `7`: `created_at`
- `10`: `chunking`
- `11`: `input_origin`
- `12`: `input_roots`

Rules:

- `version` is the only schema/version field in v1.
- `index` is an unsigned integer and must be `>= 1` for all actual extensions.
- `parent_doc_hash` and `root_doc_hash` are stored as full 32-byte binary values.
- `created_at` is an integer Unix epoch seconds timestamp.
- Valid v1 extensions require an unsealed root backup.
- `input_origin` is a string in `{"file", "directory", "mixed"}`.
- `input_roots` is a list of non-empty UTF-8 leaf labels and each element must not contain `/` or
  `\\`.
- cross-field consistency for `input_origin` and `input_roots` matches the current root manifest
  contract:
  - `input_origin = "file"` => `input_roots` must be empty
  - `input_origin = "directory"` or `"mixed"` => `input_roots` must be non-empty
- decoders must reject invalid types, invalid enum values, and cross-field inconsistencies in V2
  header fields
- `chain_id` is derived from the root backup identity at runtime and is not persisted in the
  extension header.

### Body Field Keys

Use integer keys in `BODY_CBOR`:

- `1`: `files`
- `2`: `chunks`

## Envelope V2 Structural Bounds and Ordering

`Envelope V2` keeps the same fail-closed posture as the current stable format.

Rules:

- V2 file paths are always stored directly as normalized strings; v1 does not define a
  prefix-table path encoding for extension file recipes.
- every file `path` must satisfy the same normalized relative-path constraints as current manifest
  paths
- `files` must be non-empty and must contain `<= MAX_MANIFEST_FILES` entries.
- duplicate file `path` values inside one extension are invalid.
- `files` entries are ordered by normalized `path` ascending.
- `size` is a non-negative integer.
- zero-length files must use an empty `chunk_refs` list.
- non-empty files must use a non-empty `chunk_refs` list whose `uncompressed_len` values sum
  exactly to `size`.
- each `chunk_ref.uncompressed_len` must be a positive integer and must match the resolved chunk's
  decoded length exactly.
- each chunk record `raw_len` must be a positive integer and must equal the decoded uncompressed
  chunk length exactly.
- after chunk resolution, the reconstructed file bytes for each entry must hash to that file
  entry's `sha256` exactly.
- the total reconstructed logical bytes for a selected recovery target must remain
  `<= MAX_DECOMPRESSED_PAYLOAD_BYTES`.
- decoders must reject non-canonical CBOR, duplicate chunk records, duplicate file paths, size
  mismatches, and any extension whose decoded structures exceed the active shared bounds.

## Chunking Strategy

Use content-defined chunking in v1.

Recommended default profile:

- algorithm family: FastCDC-style CDC
- target chunk size: 64 KiB
- minimum chunk size: 16 KiB
- maximum chunk size: 256 KiB

Store chunking as a fixed 4-item array in header field `10`:

```text
[algorithm_id, target_size, min_size, max_size]
```

Lock in:

- `algorithm_id` is numeric
- `1 = FastCDC`
- extension `01` establishes the chain chunking profile
- all later extensions in the same chain must use the exact same chunking profile
- root virtual chunkization uses that same locked profile

## File Recipe Model

Each file entry in `BODY_CBOR[1]` is a fixed array:

```text
[path, size, sha256, mtime, chunk_refs]
```

Where:

- `path` is the normalized stored path
- `size` is the logical file byte length
- `sha256` is the file hash as raw 32-byte binary
- `mtime` is the stored mtime or `null`
- `chunk_refs` is the ordered chunk reference list

Each `chunk_ref` is a fixed array:

```text
[chunk_id, uncompressed_len]
```

Where:

- `chunk_id = SHA-256(uncompressed_chunk_bytes)` stored as raw 32-byte binary
- `uncompressed_len` is the uncompressed chunk length

When a path is changed, the extension stores the full new chunk-ref list for that path. It does not
store patch operations against the previous recipe.

## Chunk Record Model

Each chunk entry in `BODY_CBOR[2]` is a fixed array:

```text
[chunk_id, codec, raw_len, data]
```

Where:

- `chunk_id = SHA-256(uncompressed_chunk_bytes)` stored as raw 32-byte binary
- `codec` is numeric:
  - `0 = raw`
  - `1 = gzip`
- `raw_len` is the uncompressed chunk length
- `data` is the stored bytes

Rules:

- `chunk_id` is always computed as `SHA-256(uncompressed_chunk_bytes)`, regardless of codec.
- v1 supports both `raw` and `gzip` chunk storage from day one.
- `chunks` contains only newly introduced chunks for that extension.
- Duplicate `chunk_id` records inside one extension are invalid.
- `chunks` entries are ordered by `chunk_id` ascending on the raw 32-byte value.
- A file recipe referencing an unresolved `chunk_id` is a hard invalid-chain error.
- For `codec = raw`:
  - `len(data)` must equal `raw_len`.
- For `codec = gzip`:
  - decoders must enforce a complete gzip stream
  - decoders must reject trailing bytes after the gzip stream
  - decoders must reject output that exceeds `raw_len` during decompression
  - final decompressed length must equal `raw_len` exactly
- Decoders must reject chunk records whose decoded uncompressed bytes do not hash to `chunk_id`.
- Decoders must apply chunk-level decompression and hash validation before recipe reconstruction.

## Delta Semantics

The root standalone backup is the only full base state in v1.

Each extension stores only:

- extension metadata
- file recipes for changed or new paths
- newly introduced chunks

Rules:

- paths omitted from an extension are inherited unchanged
- paths present in an extension replace the previous recipe for that path
- add vs replace is inferred from prior reconstructed state
- no explicit file operation field is needed in v1
- no delete support
- no rename support

### Virtual Root Chunk Source

The root backup remains `Envelope V1` and is not rewritten, but it still participates in chunk
reuse.

Rules:

- the root backup acts as a virtual chunk source for the chain
- on `extend` and chain-aware `recover`, root files are reconstructed from `Envelope V1`
- reconstructed root files are rechunked in memory using the chain's locked chunking profile
- virtual root chunks use the same `chunk_id` derivation as extension chunks
- extension `01` may reference those virtual root chunks without persisting them again
- chunk resolution order is:
  - current extension chunks
  - prior validated extension chunks
  - virtual root chunks derived from the root backup
- no persisted root-side chunk index or cache is introduced in v1

## Decryption and Signing Authority Rules

Extensions inherit the root backup's decryption secret policy exactly.

Decryption continuity rules:

- the root backup passphrase is the chain-wide decryption secret for v1
- every extension ciphertext must be decryptable with that same passphrase
- if passphrase shard PDFs are emitted for an extension, they must reconstruct that same
  chain-wide passphrase
- recovery and inspect flows resolve one passphrase for the validated chain and use it for the
  selected target extension
- v1 excludes passphrase rotation and mixed-passphrase extension lines

Extensions are authenticated-only.

Authority resolution:

- unsealed root backup:
  - recover signing seed from the embedded manifest state
- sealed root backup:
  - not extendable in v1
  - sealed backups discard signing authority, and the current backup surface does not emit
    signing-key shard documents for sealed roots

- `extend` against a sealed root must fail before diffing, chunking, or writes with
  `SEALED_ROOT_NOT_EXTENDABLE`.
- For supported unsealed roots, if signing authority cannot be recovered, extension is rejected
  before diffing, chunking, or writing output artifacts.

The top-level non-goals apply here directly: no unsigned mode, no passphrase rotation, no mixed
authority lines, and no authority rotation in v1.

## Extension Discovery and Validation

Discovery is artifact-driven.

Layout:

```text
backup-root/
  qr_document.pdf
  recovery_document.pdf
  ...
  extensions/
    01/
      qr_document-01-<docid>.pdf
      recovery_document-01-<docid>.pdf
      ...
    02/
      qr_document-02-<docid>.pdf
      recovery_document-02-<docid>.pdf
      ...
```

Discovery rules:

- only directories matching `^(0[1-9]|[1-9][0-9]{1,})$` are candidate extensions
- non-directory entries and non-authoritative staging entries under `extensions/` are ignored by
  discovery
- decimal-named directories under `extensions/` that are not canonical extension renderings remain
  invalid and must be rejected during validation rather than silently ignored
- `extend` must stage new outputs under a non-canonical temporary directory such as
  `extensions/.staging-<index>-<nonce>/`
- staging directory names must never match the canonical extension directory regex
- a staged extension becomes authoritative only after all required artifacts are written and both
  MAIN carriers are re-validated against the new extension's authenticated identity
- before publish, the staged directory must also pass full extension-directory validity checks for
  the chosen render and output policy of that extension, including required shard/signing-key shard
  artifacts when those outputs are in scope
- publish into `extensions/<dir_name>/` must happen as one final atomic rename within the same
  filesystem
- write path auto-creates the canonical `extensions/<dir_name>/` directory from the computed
  `index`, where `dir_name` is base-10 with minimum width `2`
- extension artifact filenames inside `extensions/<dir_name>/` use the form
  `<doctype>-<dir_name>-<docid>...`
- read path treats `dir_name` and filename `N` as discovery/order hints only, then cross-checks them
  against the decrypted authenticated `index`

Write-path publish validation rules:

- newly rendered staged extensions must contain `qr_document-<N>-<docid>.pdf`
- newly rendered staged extensions must contain `recovery_document-<N>-<docid>.pdf`
- `recovery_kit_index-<N>-<docid>.pdf` is required at publish time only when the chosen design for that
  generation supports it
- passphrase shard PDFs are required at publish time only when that generation is configured to emit
  passphrase sharding
- signing-key shard PDFs are required at publish time only when that generation is configured to
  emit signing-key sharding
- a staged extension missing required publish-time artifacts is invalid and must not be promoted

Read-path discovery and validation rules:

- MAIN recovery carriers are authoritative for extension discovery and lineage validation
- a candidate canonical extension directory must provide both payload MAIN carriers:
  `qr_document-<N>-<docid>.pdf` and `recovery_document-<N>-<docid>.pdf`
- a candidate extension is invalid if either payload MAIN carrier is missing or cannot provide
  recoverable MAIN data
- both payload MAIN carriers must independently remain recoverable; disagreement is a hard
  invalid-chain error
- after MAIN recovery, the derived ciphertext `doc_id` must match the filename `docid` for every
  authoritative carrier
- missing optional render-policy artifacts do not by themselves invalidate discovery or lineage
  validation
- missing shard PDFs or signing-key shard PDFs may reduce available unlock methods or surface
  warnings/blocking issues, but they do not make an otherwise recoverable extension structurally
  invalid
- incomplete staging directories are non-authoritative and must be ignored by discovery because they
  never use canonical directory names
- partial or corrupt canonical extension directories are rejected when they cannot provide
  recoverable MAIN data or authenticated lineage

Lineage validation rules:

- root backup is conceptual `index = 0`
- extensions must be sequential with no gaps
- duplicate indexes are rejected
- directory number and filename `N` must match the internal authenticated `index`
- `parent_index` must equal the previous validated state index
- `parent_doc_hash` must bind to the exact previous validated state
- `root_doc_hash` must match the root backup `doc_hash`
- `chain_id` must match the deterministic chain id derived from the root backup
- v1 extension chains are valid only for unsealed roots
- `sealed` must be `false` for every valid v1 extension
- `signing_seed` must equal the unsealed root backup signing seed bytes
- the extension `01` chunking profile becomes the chain-wide chunking profile
- later extensions must match that locked chunking profile exactly

## Extend Flow

`extend` should execute this sequence:

1. Resolve and validate the root backup.
2. Discover and validate existing extensions.
3. Reject sealed root backups; `extend` is supported only for unsealed roots in v1.
4. Resolve authentication and signing authority from the embedded root manifest state.
5. If recover-style scan/payload inputs were supplied, require the writable root backup directory
   target to authenticate to the same root identity (`doc_hash` and derived `doc_id`) before any
   staging or writes begin.
6. Fully decrypt and reconstruct current logical state.
7. Rechunk root files in memory as needed to establish the virtual root chunk source.
8. Read user-selected local input scope using `--input`, `--input-dir`, and `--base-dir`.
9. Compare current reconstructed state against selected local inputs within scope.
10. Detect added and updated paths.
11. Rechunk changed/new file content.
12. Build new file recipes for changed/new paths.
13. Render the extension artifact set into a non-canonical staging directory under `extensions/`
    using the chosen backup-style render/config inputs.
14. Re-validate both MAIN carriers, validate the full staged artifact set required by the chosen
    render and output policy for that extension, and atomically promote the staged directory to the computed canonical
    `extensions/<dir_name>/` directory.

Behavior rules:

- selected local inputs are the only source of new desired state in v1
- extending from another backup is not supported in v1
- `extend` targets a writable root backup directory, not an arbitrary recover-style scan input
- recover-style root parsing is reused internally for read/unlock logic only
- `extend` requires at least one explicit local content input via `--input` or `--input-dir`
- sealed roots are terminal in v1 and must fail with `SEALED_ROOT_NOT_EXTENDABLE`
- if recover-style scan/payload inputs are provided, they must resolve to the same authenticated
  root identity as the writable root backup directory target or `extend` must fail before writing
- render/config overrides follow the same resolution model as `backup` and apply only to the new
  extension generation
- failed or interrupted writes must leave the prior validated chain head untouched and recoverable
- if nothing changed, `extend` fails with a stable no-op error
- if a previously backed path inside selected scope is now missing locally, `extend` fails because
  delete/rename semantics are unsupported in v1

## Recover Flow

`recover` accepts:

- one standalone backup root with optional appended extensions

Default behavior:

- recover the latest state

Optional selectors:

- `--extension-index <n>`
- `--extension-doc-hash <hex>`

Recovery flow:

1. Validate the root backup.
2. Discover and validate extensions.
3. Select latest extension by default, or the requested target extension.
4. Start from root backup state.
5. Rechunk root files in memory as needed to establish the virtual root chunk source.
6. Overlay extension file recipe replacements in order through the selected target.
7. Resolve chunks from the current extension, prior validated state, or the virtual root chunk
   source as needed.
8. Rebuild files and verify `sha256`.
9. Write recovered output.

## Transport and Size Constraints

The current single-ciphertext transport bound remains authoritative in v1.

This means:

- each extension must fit current MAIN ciphertext limits
- `extend` must fail if the resulting extension would exceed current transport bounds

To avoid a dead-end when a chain outgrows the current delta envelope size, v1 includes explicit
compaction-by-rebase.

Compaction rules:

- `compact` fully reconstructs the latest logical state of an existing root-plus-extensions chain
- `compact` writes that latest state as a fresh standalone backup root in a separate output
  directory
- `compact` preserves the chain-wide passphrase; it is not a passphrase-rotation surface in v1
- `compact` preserves the root backup sealed/unsealed state exactly
- if the root backup is unsealed, the compacted standalone backup must carry the same signing seed
  bytes as the root backup
- if the root backup is sealed, `compact` does not require prior signing authority once the latest
  logical state has been recovered; it emits a fresh sealed standalone backup and discards the new
  signing key the same way `backup --sealed` does
- passphrase shard and signing-key shard output policy defaults to the current root backup policy,
  subject to sealed semantics; sealed compacted outputs never emit signing-key shard documents
- rendered artifact design/config defaults for the compacted output follow the same backup-style
  config resolution surface used by `backup` and `extend`
- the original root backup and all of its extension directories remain unchanged and recoverable
- if the compacted output is unsealed, it is a normal standalone backup that can start a new
  extension line
- if the compacted output is sealed, it remains terminal for `extend` in v1
- compaction is the supported v1 escape hatch when future deltas would otherwise exceed the current
  transport bound
- current implementation exposes `estimated_extension_bytes` during inspect; a low-headroom warning
  that proactively directs operators to `compact` remains future work
- v1 compaction does not mutate or delete prior generations in place

## CLI Surface

User-facing commands:

- `ethernity extend`
- `ethernity compact`

Suggested `extend` inputs:

- required writable root backup directory target
- root backup directory target is the only write target for `extend`
- recover-style scan/payload/passphrase/auth inputs, when accepted, are read-only unlock inputs only
  and must not be treated as alternate write targets
- passphrase or passphrase shard inputs as needed
- auth inputs as needed
- content inputs:
  - `--input`
  - `--input-dir`
  - `--base-dir`
- optional output-policy overrides matching `backup`:
  - `--shard-threshold`
  - `--shard-count`
  - `--signing-key-mode`
  - `--signing-key-shard-threshold`
  - `--signing-key-shard-count`
- optional render/config overrides matching `backup`:
  - `--config`
  - `--paper`
  - `--design`
  - `--qr-chunk-size`
  - `--layout-debug-dir`
- absent output-policy overrides inherit the current root backup's passphrase-sharding and
  signing-key-sharding policy for the newly rendered extension
- signing-key sharding remains subject to the current backup rules:
  - it requires passphrase sharding
  - it is invalid for sealed roots
- output-policy overrides affect only the newly rendered extension and do not rewrite prior
  generations

Suggested `compact` inputs:

- required existing root backup directory target
- required output directory for the rebased standalone backup
- recover-style parsing reused internally for read/unlock logic where applicable
- passphrase or passphrase shard inputs as needed
- auth inputs as needed
- optional render/config overrides matching `backup`:
  - `--config`
  - `--paper`
  - `--design`
  - `--qr-chunk-size`
  - `--layout-debug-dir`
- compact does not accept passphrase-rotation or signing-authority-rotation inputs in v1
- compact should reuse the current root backup shard/signing policy by default rather than requiring
  operators to restate it, subject to sealed semantics

## API Surface

Do not overload existing inspect contracts.

Add:

- `ethernity api extend`
- `ethernity api inspect extend`

### API Started Args

Mirror current API style. Include:

- `config`
- `paper`
- `design`
- writable root backup directory target as a dedicated path field
- `base_dir`
- `input`
- `input_dir`
- `qr_chunk_size`
- `layout_debug_dir`
- `shard_threshold`
- `shard_count`
- `signing_key_mode`
- `signing_key_shard_threshold`
- `signing_key_shard_count`
- recover-style scan/payload/passphrase/auth/shard fields reused only as read/unlock inputs where
  applicable
- auth input fields
- shard input fields
- `has_passphrase`
- `quiet`
- `debug`

Do not include derived state such as resolved head, diff summary, or chunk reuse in `started`.

### API Inspect Extend Result

Recommended top-level fields:

- `operation`
- `doc_id`
- `input_label`
- `input_detail`
- `input_kind`
- `source_summary`
- `frame_counts`
- `root_doc_id`
- `root_doc_hash`
- `chain_id`
- `auth_status`
- `unlock`
- `discovered_extension_dirs`
- `validated_head_index`
- `available_extensions`
- `ancestry_valid`
- `signing_authority`
- `selected_scope`
- `diff_summary`
- `chunk_reuse`
- `estimated_extension_bytes`
- `blocking_issues`
- `warnings`

Recommended nested objects:

- `unlock`
  - `mode`
  - `passphrase_provided`
  - `validated_shard_count`
  - `required_shard_threshold`
  - `satisfied`
- `signing_authority`
  - `available`
  - `satisfied`
  - `source`
    - `embedded_seed`
    - `null` until authority resolution succeeds
- `selected_scope`
  - `files`
  - `directories`
  - `base_dir`
- `diff_summary`
  - `changed_paths`
  - `new_paths`
  - `updated_paths`
- `chunk_reuse`
  - `reused_chunks`
  - `new_chunks`

Recommended collection shapes:

- `available_extensions`
  - array of objects:
    - `dir_name`
    - `doc_id`
    - `doc_hash`
- `blocking_issues`
  - array of:
    - `code`
    - `message`
    - `details`
- `warnings`
  - array of:
    - `code`
    - `message`
    - `details`

Rules:

- inspect result must include `operation: "inspect"` so it follows the existing inspect-event
  discriminator contract used by current NDJSON clients
- inspect result should preserve the existing inspect-recover/mint context shape by including
  `doc_id`, `input_label`, `input_detail`, `source_summary`, and `frame_counts`, then add
  extend-specific fields additively
- `input_kind` values are:
  - `standalone_root`
  - `extended_root`
- `auth_status` should follow the existing inspect auth-status semantics already documented for
  `recover` and `mint`
- inspect is read-only
- inspect emits no artifact events
- inspect fully decrypts and reconstructs current state when auth/unlock are satisfied
- inspect may be invoked with or without local content scope
- `doc_id` should mirror the root backup `doc_id` so existing inspect clients can treat the primary
  inspected document identity consistently
- `root_doc_id`, `root_doc_hash`, `chain_id`, `available_extensions[].doc_id`, and
  `available_extensions[].doc_hash` must be emitted as lowercase hex strings with no `0x` prefix
- `source_summary` should follow the existing inspect contract: it may stay `null` until
  decrypt-dependent root-state summary data is available
- `frame_counts` should follow the existing inspect contract and report the decoded root input
  transport counts used for inspection
- `unlock` should mirror the existing inspect-recover readiness shape so callers can distinguish
  passphrase, shard, and auth gating without parsing free-form errors
- fields that require decrypted current-state analysis and authenticated chain validation, but not
  local scope, are nullable until unlock/auth is satisfied and chain validation succeeds:
  - `validated_head_index`
  - `ancestry_valid`
- fields that require decrypted current-state analysis plus explicit local content scope are nullable
  until unlock/auth is satisfied, chain validation succeeds, and local scope is provided:
  - `diff_summary`
  - `chunk_reuse`
  - `estimated_extension_bytes`
- `signing_authority.source` must stay `null` until the signing authority has been resolved from the
  embedded seed
- `selected_scope` is `null` when no local scope flags were provided; otherwise it remains available
  from sanitized user inputs even when decrypt-dependent fields are `null`
- `discovered_extension_dirs` may be reported from directory discovery before decrypt-dependent
  analysis is available
- `validated_head_index` and `ancestry_valid` must reflect authenticated lineage validation only and
  must stay `null` until the chain has been decrypted and validated through the selected head
- `available_extensions` is the discovered extension inventory from artifact layout and recovered
  MAIN ciphertext ids; callers must not treat it as authenticated lineage proof until validated-chain
  fields are available
- inspect without local scope must not raise `EXTENSION_INPUT_REQUIRED`; it is a valid chain-only
  inspection mode
- inspect should surface `SEALED_ROOT_NOT_EXTENDABLE` as a blocking issue for sealed roots
- unsupported delete/rename-in-scope appears as a blocking issue

### API Extend Result

Recommended fields:

- `index`
- `doc_id`
- `doc_hash`
- `root_doc_id`
- `root_doc_hash`
- `chain_id`
- `extension_dir`
- `artifacts`
- `selected_scope`
- `diff_summary`
- `chunk_reuse`
- `extension_bytes`

Rules:

- emit one `artifact` event per generated output file
- when `layout_debug_dir` is enabled, emit layout sidecars as `artifact` events with kind
  `layout_debug_json`, matching the existing backup API behavior
- emit a final `result` object listing extension identity and generated artifact paths
- expose `index`, `doc_id`, and `doc_hash`
- `doc_id`, `doc_hash`, `root_doc_id`, `root_doc_hash`, and `chain_id` must be emitted as
  lowercase hex strings with no `0x` prefix

Recommended `artifacts` shape:

- `qr_document`
- `recovery_document`
- `recovery_kit_index`
- `shard_documents`
- `signing_key_shard_documents`
- layout debug sidecars are not listed in `artifacts`; they are reported only through
  `layout_debug_json` artifact events when enabled

## Stable Error and Blocking Codes

Recommended v1 code set:

- `EXTENSION_INPUT_REQUIRED`
- `SEALED_ROOT_NOT_EXTENDABLE`
- `NO_CHANGES_DETECTED`
- `CHAIN_INVALID`
- `EXTENSION_INDEX_MISMATCH`
- `PATH_REMOVAL_NOT_SUPPORTED`
- `SIGNING_AUTHORITY_UNAVAILABLE`
- `EXTENSION_TOO_LARGE`
- `PASSPHRASE_ROTATION_NOT_SUPPORTED`
- `ROOT_BACKUP_INVALID`
- `EXTENSION_DECRYPT_FAILED`

Use the same underlying reason in inspect blocking issues and execute-time failures where applicable.

## Format Change Set

Implementation requires these format updates:

- add `Envelope V2`
- specify `Envelope V2` header and body structures
- specify extension lineage metadata
- specify file recipe encoding
- specify chunk record encoding
- specify V2 path ordering and shared resource bounds
- specify extension directory discovery and validation semantics
- specify must-reject negative cases for unresolved chunks, ancestry mismatch, and root mismatch
- document compatibility behavior between old and new decoders
- add a new entry to `docs/format_changes.md`

Likely not required in v1:

- new frame version
- new AUTH payload version
- new shard payload version
- new fallback grammar

## Draft Normative Text Targets

When Phase 6 updates the live normative documents, use this plan as the draft source for those
changes.

### Draft `docs/format.md` Deltas

Add a new versioned extension envelope section alongside the current `Envelope V1` section:

- define `Envelope V2` as:
  - `MAGIC`
  - `VERSION = 2`
  - `HEADER_LEN`
  - `HEADER_CBOR`
  - `BODY_LEN`
  - `BODY_CBOR`
- require canonical uvarints for `VERSION`, `HEADER_LEN`, and `BODY_LEN`
- require canonical CBOR for both `HEADER_CBOR` and `BODY_CBOR`
- specify `HEADER_CBOR` integer-keyed map fields:
  - `1`: `version`
  - `2`: `index`
  - `3`: `parent_index`
  - `4`: `parent_doc_hash`
  - `5`: `root_doc_hash`
  - `6`: `chain_id`
  - `7`: `created_at`
  - `8`: `sealed`
  - `9`: `signing_seed`
  - `10`: `chunking`
  - `11`: `input_origin`
  - `12`: `input_roots`
- require valid v1 extensions to target only unsealed roots
- require every valid v1 extension to set `sealed=false` and `signing_seed` equal to the root
  signing seed bytes
- require `created_at` to be integer Unix epoch seconds
- require `input_origin` to be one of `file`, `directory`, or `mixed`
- require `input_roots` entries to be non-empty UTF-8 leaf labels containing no `/` or `\\`
- require the same `input_origin` / `input_roots` cross-field consistency rules as `Envelope V1`
- specify `BODY_CBOR` integer-keyed map fields:
  - `1`: `files`
  - `2`: `chunks`
- require V2 file paths to be direct normalized strings; no prefix-table path encoding in v1
- require every V2 file `path` to satisfy the same normalized relative-path constraints used by the
  current manifest path validation rules
- define `chunking` as `[algorithm_id, target_size, min_size, max_size]`
- define `algorithm_id = 1` as FastCDC
- require extension `01` to establish the chain-wide chunking profile
- require later extensions to match that chunking profile exactly
- define file entries as `[path, size, sha256, mtime, chunk_refs]`
- require `files` to be non-empty, contain no duplicate `path` values, contain
  `<= MAX_MANIFEST_FILES` entries, and be ordered by normalized `path`
- define chunk refs as `[chunk_id, uncompressed_len]`
- require zero-length files to use empty `chunk_refs`
- require non-empty files to use `chunk_refs` whose `uncompressed_len` values sum exactly to `size`
- require reconstructed file bytes to hash to the file entry `sha256` exactly
- define chunk records as `[chunk_id, codec, raw_len, data]`
- define codec ids:
  - `0 = raw`
  - `1 = gzip`
- require `chunk_id = SHA-256(uncompressed_chunk_bytes)` stored as raw 32-byte binary
- require `chunks` to contain no duplicate `chunk_id` values and to be ordered by `chunk_id`
  ascending on the raw 32-byte value
- require chunk record validation rules:
  - `codec = raw` => `len(data) == raw_len`
  - `codec = gzip` => complete gzip stream, no trailing bytes, no inflation past `raw_len`, and
    final decompressed length exactly `raw_len`
- require decoders to validate `SHA-256(decoded_uncompressed_chunk_bytes) == chunk_id` before chunk
  reuse or file reconstruction
- require `chunk_ref.uncompressed_len` and chunk-record `raw_len` to match resolved decoded chunk
  lengths exactly
- require reconstructed logical bytes for a selected target to remain
  `<= MAX_DECOMPRESSED_PAYLOAD_BYTES`
- require extension directories to be discovered from canonical `extensions/<dir_name>/` names, where
  `dir_name` is the decimal extension index padded to minimum width `2`
- require candidate extension directories to match `^(0[1-9]|[1-9][0-9]{1,})$`
- require new extensions to be rendered under non-canonical staging directories and promoted into
  canonical names only by final atomic rename after artifact validation succeeds
- require publish-time artifact completeness checks to be evaluated against the new generation's
  chosen render/sharding policy only
- require the root standalone backup to remain the conceptual base state with `index = 0`
- require in-place extension ancestry validation using:
  - `index`
  - `parent_index`
  - `parent_doc_hash`
  - `root_doc_hash`
  - deterministic `chain_id`
- require valid v1 extension chains to root at an unsealed backup
- require `chain_id = BLAKE2b-256("ETHERNITY-CHAIN-V1" || root_doc_hash)`
- require omitted paths to be inherited unchanged
- require mentioned paths to replace the prior file recipe for that path
- require `chunks` to contain only newly introduced chunks for the extension
- require virtual root chunkization from reconstructed `Envelope V1` root files when resolving base
  chunk reuse
- require read-path discovery and lineage validation to treat recoverable MAIN carriers as
  authoritative, not optional render-policy artifacts
- require hard rejection for:
  - unresolved `chunk_id`
  - directory/index mismatch
  - non-canonical extension directory rendering
  - ancestry gaps
  - `root_doc_hash` mismatch
  - `chain_id` mismatch
  - any extension rooted at a sealed standalone backup
  - root/extension signing-seed mismatch

### Draft `docs/cli_api.md` Deltas

When the command surfaces are implemented, extend the CLI API docs to add:

- `ethernity api extend`
- `ethernity api inspect extend`

Document these started/result contracts:

- `api inspect extend`
  - read-only
  - no artifact events
  - emits `operation: "inspect"` on the final result event
  - fully decrypts and reconstructs current state when unlock/auth is satisfied
  - preserves the existing inspect context fields `doc_id`, `input_label`, `input_detail`,
    `source_summary`, and `frame_counts`
  - exposes `auth_status` plus structured `unlock` readiness like existing inspect APIs
  - emits `root_doc_id`, `root_doc_hash`, `chain_id`, `available_extensions[].doc_id`, and
    `available_extensions[].doc_hash` as lowercase hex strings with no `0x` prefix
  - supports chain-only inspection with no local scope inputs
  - returns `validated_head_index` and `ancestry_valid` as `null` until authenticated chain
    validation succeeds
  - returns `selected_scope`, `diff_summary`, `chunk_reuse`, and `estimated_extension_bytes` as
    `null` until decrypt-dependent analysis is available and local scope inputs are provided
  - keeps `signing_authority.source = null` until authority resolution succeeds
  - returns:
    - `operation`
    - `doc_id`
    - `input_label`
    - `input_detail`
    - `input_kind`
    - `source_summary`
    - `frame_counts`
    - `root_doc_id`
    - `root_doc_hash`
    - `chain_id`
    - `auth_status`
    - `unlock`
    - `discovered_extension_dirs`
    - `validated_head_index`
    - `available_extensions`
    - `ancestry_valid`
    - `signing_authority`
    - `selected_scope`
    - `diff_summary`
    - `chunk_reuse`
    - `estimated_extension_bytes`
    - `blocking_issues`
    - `warnings`
- `api extend`
  - emits one artifact event per generated output file
  - when `layout_debug_dir` is set, emits layout sidecars as `layout_debug_json` artifact events,
    consistent with the existing backup API
  - emits `doc_id`, `doc_hash`, `root_doc_id`, `root_doc_hash`, and `chain_id` as lowercase hex
    strings with no `0x` prefix
  - returns:
    - `index`
    - `doc_id`
    - `doc_hash`
    - `root_doc_id`
    - `root_doc_hash`
    - `chain_id`
    - `extension_dir`
    - `artifacts`
    - `selected_scope`
    - `diff_summary`
    - `chunk_reuse`
    - `extension_bytes`

### Draft `docs/cli_api.schema.json` Deltas

Add new schema branches for:

- `extendStartedEvent`
- `inspectExtendStartedEvent`
- `extendResultEvent`
- `inspectExtendResultEvent`

Add command/enum support for:

- command `extend`
- `input_kind`:
  - `standalone_root`
  - `extended_root`
- `signing_authority.source`:
  - `embedded_seed`
  - `null` while unresolved
- extend started args:
  - `shard_threshold`
  - `shard_count`
  - `signing_key_mode`
  - `signing_key_shard_threshold`
  - `signing_key_shard_count`

Add documented error and blocking code support for:

- `EXTENSION_INPUT_REQUIRED`
- `SEALED_ROOT_NOT_EXTENDABLE`
- `NO_CHANGES_DETECTED`
- `CHAIN_INVALID`
- `EXTENSION_INDEX_MISMATCH`
- `PATH_REMOVAL_NOT_SUPPORTED`
- `SIGNING_AUTHORITY_UNAVAILABLE`
- `EXTENSION_TOO_LARGE`
- `PASSPHRASE_ROTATION_NOT_SUPPORTED`
- `ROOT_BACKUP_INVALID`
- `EXTENSION_DECRYPT_FAILED`

Recommended exact object shapes:

- inspect result root
  - `operation = "inspect"`
  - `doc_id`
  - `input_label`
  - `input_detail`
  - `input_kind`
  - `source_summary`
  - `frame_counts`
  - `root_doc_id`
  - `root_doc_hash`
  - `chain_id`
  - `auth_status`
  - `unlock`
  - `discovered_extension_dirs`
  - `validated_head_index`
  - `available_extensions`
  - `ancestry_valid`
  - `signing_authority`
  - `selected_scope`
  - `diff_summary`
  - `chunk_reuse`
  - `estimated_extension_bytes`
  - `blocking_issues`
  - `warnings`
- `unlock`
  - `mode`
  - `passphrase_provided`
  - `validated_shard_count`
  - `required_shard_threshold`
  - `satisfied`
- `selected_scope`
  - `files`
  - `directories`
  - `base_dir`
  - or `null` when no local scope was requested
- `diff_summary`
  - `changed_paths`
  - `new_paths`
  - `updated_paths`
- `chunk_reuse`
  - `reused_chunks`
  - `new_chunks`
- `available_extensions[]`
  - `dir_name`
  - `doc_id`
  - `doc_hash`
- `signing_authority`
  - `available`
  - `satisfied`
  - `source`
- `api extend` artifact events must also allow `layout_debug_json` when `layout_debug_dir` is
  enabled, while the final `artifacts` object continues to list only the primary backup/shard
  outputs

Schema notes:

- `root_doc_id`, `doc_id`, and `available_extensions[].doc_id` should reuse the existing lowercase
  hex-string `doc_id` schema pattern
- `root_doc_hash`, `doc_hash`, `available_extensions[].doc_hash`, and `chain_id` should use
  lowercase fixed-length hex-string schemas
- `signing_authority.source` must allow `null` until authority resolution succeeds

## Testing Plan

Unit tests:

- CDC determinism and boundary stability
- `Envelope V2` header and body encoding/decoding
- non-canonical `Envelope V2` CBOR rejection for both header and body
- V2 file path validation, duplicate-path rejection, and deterministic ordering
- deterministic chunk-record ordering by `chunk_id`
- file recipe encoding and decoding
- chunk record encoding and decoding
- chunk id derivation from uncompressed bytes
- raw and gzip chunk validation, including trailing-byte rejection and exact `raw_len` enforcement
- file-level `sha256` verification after chunk reconstruction
- shared-bounds enforcement for oversized decoded V2 structures and reconstructed logical bytes
- chain id derivation from root doc hash
- explicit-path diff logic
- no-op extend detection
- ancestry validation
- unresolved chunk rejection
- passphrase continuity across root and extensions
- authority gating for unsealed roots and explicit sealed-root rejection for `extend`
- compacting a sealed root produces a fresh sealed standalone backup with no signing-key shard output

Integration tests:

- extend existing standalone backup in place
- first extension at `extensions/01`
- multiple sequential extensions with no gaps
- interrupted extend leaves only a non-canonical staging directory and does not poison later
  discovery or recovery
- extend rejected for a sealed root backup
- read-path recovery/inspection remains valid when optional non-authoritative render artifacts are
  absent but a MAIN carrier is still recoverable
- canonical extension directories with disagreeing `qr_document-<N>-<docid>.pdf` and
  `recovery_document-<N>-<docid>.pdf`
  MAIN payloads are rejected as an invalid chain
- extension filenames whose `docid` does not match recovered ciphertext identity are rejected
- single-file update with chunk reuse
- mixed additions and updates
- latest restore
- selected-extension restore by index
- selected-extension restore by doc hash
- unsupported path removal in selected scope
- extend rejection on attempted passphrase rotation
- compact latest state into a fresh standalone root
- extend after compaction on a new unsealed root
- extend rejected after compaction when the compacted output is sealed
- no persisted sidecar artifacts created

E2E and contract tests:

- CLI extend flows
- CLI compact flow
- API extend NDJSON schema and execution flows
- API extend emits `layout_debug_json` artifact events when `layout_debug_dir` is enabled
- API inspect extend NDJSON schema
- API inspect extend preserves the existing inspect context fields while adding extend-specific
  fields additively
- API inspect extend reports `discovered_extension_dirs` before decrypt, but keeps validated lineage
  fields `null` until authenticated chain validation succeeds
- API inspect extend without local scope returns chain inspection with `selected_scope`,
  `diff_summary`, `chunk_reuse`, and `estimated_extension_bytes` as `null` while still allowing
  `validated_head_index` and `ancestry_valid` after chain validation succeeds
- recovery extension selection
- docs and format coverage

Closeout verification:

- `uv run pyright`
- `uv run check-jsonschema --check-metaschema docs/cli_api.schema.json`
- `uv run typos .`
- `cd kit && npm run lint`
- `cd kit && npm run format:check`
- `cd kit && npm test`
- `uv run ruff check src tests`
- `uv run mypy src`
- `uv run pytest tests/unit -q`
- `uv run pytest tests/integration -q`
- `uv run pre-commit run --all-files`

## Implementation Milestones

Milestone 0: Plan lock

Scope:
- keep this planning document aligned with the agreed storage model
- keep delta extensions, compaction-by-rebase, passphrase continuity, and the no-sidecar invariant
  explicit

Done when:
- the implementation team can build against this document without reopening product-shape questions

Milestone 1: `Envelope V2` and chain identity

Deliver:
- `Envelope V2` types and codecs
- deterministic `chain_id` derivation
- shared signing-authority resolution for `extend`
- strict validation for header/body typing, chunk ids, and bounds

Done when:
- one extension document can be encoded, decoded, and authenticated in isolation

Milestone 2: Extension state model

Deliver:
- chunking abstraction and chunk record storage
- file recipe storage and reconstruction
- virtual-root chunk reuse
- lineage validation driven by decrypted metadata
- directory/filename cross-checking against authenticated `index` and `doc_id`

Done when:
- the runtime can validate a root plus extension chain and reconstruct the logical latest state

Milestone 3: Write path

Deliver:
- `extend`
- staged writes under non-canonical `.staging-*` directories
- render/output-policy inheritance and overrides
- final publish validation and atomic promotion into `extensions/<NN>/`
- operator-facing `<doctype>-<N>-<docid>` filenames

Done when:
- an unsealed root can be extended in place and failed writes leave the prior chain head untouched

Milestone 4: Read path

Deliver:
- chain-aware `recover`
- extension selection by index and doc hash
- compact latest-state rebase into a fresh standalone root

Done when:
- recovery can replay validated extensions through an arbitrary selected target and compact can emit a
  fresh root with the same chain semantics

Milestone 5: API and CLI surfaces

Deliver:
- `api extend`
- `api inspect extend`
- CLI wiring for `extend` and `compact`
- NDJSON event coverage, including `layout_debug_json` artifact events when enabled
- final started-args field names for the new surfaces

Done when:
- CLI and NDJSON callers can run the extend/inspect/compact flows without relying on ad hoc output
  parsing

Milestone 6: Normative docs and release verification

Deliver:
- update `docs/format.md`
- update `docs/format_changes.md`
- update `docs/cli_api.md`
- update `docs/cli_api.schema.json`
- remove any lingering `generation` terminology that survives into implementation
- run the full verification suite in this plan

Done when:
- the implementation, live docs, schema, and tests ship as one aligned change set
