# Extension Implementation Spec

## Status

This document describes the extension feature as currently implemented in the working tree.
It is intentionally implementation-driven, not aspirational.

Primary implementation surface:

- `src/ethernity/cli/features/extend/`
- `src/ethernity/extensions/`
- `src/ethernity/formats/extension_envelope.py`
- `src/ethernity/cli/features/recover/chain.py`
- `src/ethernity/cli/features/compact/`

## Operator Surface

Implemented commands and flows:

- `ethernity extend`
- `ethernity api extend`
- `ethernity api inspect extend`
- `ethernity recover` with `--extension-index` or `--extension-doc-hash`
- `ethernity compact`

The model is append-only:

- a standalone backup root stays in place
- each new generation is written under `extensions/<nn>/`
- prior generations are not rewritten by `extend`
- `compact` materializes the latest logical state as a new standalone backup in a separate output dir

## Extend Preconditions

`extend` currently requires:

- `--root-dir`
- at least one explicit `--input` or `--input-dir`

The implementation does not support delete or rename semantics inside the selected scope.
If the selected scope omits previously backed paths, planning raises `DELETE_NOT_SUPPORTED`.

Sealed roots are terminal:

- if the root manifest is sealed, inspection emits `SEALED_ROOT_NOT_EXTENDABLE`
- execution stops before extension assembly

## Root And Chain Discovery

The feature treats `--root-dir` as a writable backup root that may contain:

- root `qr_document.pdf`
- root `recovery_document.pdf`
- optional root shard PDFs
- optional `extensions/`

Extension discovery rules implemented today:

- canonical extension dirs live under `extensions/`
- canonical names are decimal with minimum width 2, such as `01`, `02`, `10`, `100`
- non-canonical decimal names like `001` are rejected as layout errors
- staging dirs use `.staging-<index>-<nonce>`
- extension dirs must be sequential with no gaps

Within a discovered extension dir:

- both payload MAIN carriers must exist
- payload MAIN carriers are `qr_document-<nn>-<docid>.pdf` and `recovery_document-<nn>-<docid>.pdf`
- optional artifacts are `recovery_kit_index-<nn>-<docid>.pdf`, `shard-...pdf`, and `signing-key-shard-...pdf`
- filename `doc_id` values across authoritative MAIN carriers must agree

## Extension Envelope

Extensions are stored as a distinct extension envelope that uses outer envelope version `2`.

Header fields currently encoded in `HEADER_CBOR`:

- `1`: `version`
- `2`: `index`
- `4`: `parent_doc_hash`
- `5`: `root_doc_hash`
- `7`: `created_at`
- `10`: `chunking`
- `11`: `input_origin`
- `12`: `input_roots`

Validation rules:

- extension-envelope schema version is `1`
- `index` must be positive
- `parent_doc_hash` and `root_doc_hash` are 32-byte values
- `chunking` is `[algorithm_id, target_size, min_size, max_size]`
- `input_origin` must be `file`, `directory`, or `mixed`
- `input_roots` must be empty when `input_origin` is `file`
- `input_roots` must be non-empty when `input_origin` is `directory` or `mixed`
- `docs/format.md` is the normative source of truth for the wire shape

## File Model

Each changed or new file is represented as:

- normalized relative path
- logical size
- SHA-256 of the full file
- `mtime` or `null`
- ordered `chunk_refs`

The implementation stores only changed or new files in each extension document.
Unchanged files are inherited from the previously reconstructed logical state.

## Chunking And Deduplication

The chain stores a chunking profile in the extension header:

- `algorithm_id`
- `target_size`
- `min_size`
- `max_size`

Current default chunker behavior:

- empty file -> no chunks
- non-empty file -> split with a FastCDC-style rolling content-defined chunker
- `algorithm_id`, `target_size`, `min_size`, and `max_size` all participate in boundary selection

That means the current implementation uses profile-driven content-defined chunking rather than
fixed-size slicing.

Deduplication behavior:

- chunk identity is `SHA-256(uncompressed_chunk_bytes)`
- the extension builder dedupes repeated chunks within the extension
- it also dedupes against a virtual root chunk source reconstructed from the latest logical state before the new extension is built
- recovery and inspect rebuild the same virtual root chunk source when replaying the chain

## Chunk Record Encoding

Chunk records support two codecs structurally:

- `0 = raw`
- `1 = gzip`

Decoder behavior validates both codecs.
Builder behavior selects per chunk between raw and gzip.

So the current state is:

- extension-envelope decode accepts raw and gzip chunk records
- extension-envelope encode emits gzip only when it is smaller than raw for that chunk

## Extend Planning

`api inspect extend` currently does four main things:

1. discovers extension dirs
2. inspects the root backup
3. decrypts and reconstructs chain state when unlock is satisfied
4. compares the selected local scope against the reconstructed latest state

Returned inspection data includes:

- root identity
- chain identity
- discovered extension dirs
- available extension filename identities
- validated head index
- validated head AUTH status
- whether the validated head matched root-derived signing authority
- ancestry validity
- signing authority availability
- selected scope summary
- diff summary
- blocking issues

The exact JSON contract is defined by `docs/cli_api.md` and `docs/cli_api.schema.json`.

## Extend Execution

Execution flow:

1. validate inputs and root layout
2. inspect and reconstruct current chain state
3. load selected local files
4. compute changed and new paths
5. assemble an extension envelope document
6. encrypt the extension-envelope plaintext with the resolved chain passphrase
7. create a staging dir under `extensions/.staging-<index>-<nonce>`
8. render MAIN carriers with extension AUTH plus optional shard artifacts into the staging dir
9. validate the staged dir
10. atomically rename the staging dir to `extensions/<nn>/`

Inherited policy behavior:

- extend inherits whether the root emitted `recovery_kit_index.pdf`
- extend infers passphrase-shard and signing-key-shard counts from the root artifact set
- CLI overrides can replace quorum settings for the new extension only
- `--unlock-policy reuse-root` suppresses extension-local shard PDFs and relies on the root shard set
  for passphrase recovery instead
- `--unlock-policy reuse-root` currently requires passphrase shard PDFs to already exist on the root
  backup and rejects explicit shard-setting overrides for the new extension

Passphrase continuity behavior:

- the extension uses the resolved root passphrase for re-encryption
- there is no passphrase rotation feature in the implementation
- extension signing authority is derived from the embedded signing seed on an unsealed root backup,
  not embedded in the extension header

Extension AUTH behavior:

- each extension ciphertext is signed with the root-derived signing seed
- the resulting AUTH payload is rendered into the existing extension `qr_document` and
  `recovery_document`
- no separate extension AUTH artifact is created

## Publish Validation

The write path uses two validation layers before promotion:

1. filename and count validation for the staged directory
2. MAIN carrier re-scan and ciphertext identity verification

What is validated before promotion:

- staging dir name is non-canonical
- required MAIN artifacts exist
- optional shard artifacts, when required by policy, exist in the expected counts
- filenames agree on extension index and `doc_id`
- the rendered `qr_document` and `recovery_document` can be scanned back into ciphertext
- the scanned MAIN ciphertext matches the planned extension `doc_id` and `doc_hash`
- the rendered MAIN carriers provide exactly one valid AUTH payload for that ciphertext
- the extension AUTH signing key matches the root-derived signing authority

Filename/count validation still happens first, but staged promotion now also re-scans required
shard PDFs and verifies the recovered shard payloads before the final rename.

## Recovery

Recovery behavior when `--scan` points at a backup root dir:

- recover the root backup first
- discover canonical extension dirs
- default to the latest extension
- optionally stop at `--extension-index`
- optionally stop at `--extension-doc-hash`
- decrypt each selected extension with the chain passphrase
- verify each extension AUTH against the extension ciphertext `doc_hash`
- require extension AUTH to match the root-derived signing authority in authenticated mode
- validate ancestry using `root_doc_hash`, `parent_doc_hash`, and sequential indexes
- reconstruct the latest logical state by overlaying extension file recipes on the root state
- emit a synthetic V1-style manifest for the reconstructed state

The current recovery path reuses the same profile-driven content-defined chunker when reconstructing
virtual root chunks.

## Compact

`compact` is implemented as:

1. recover the latest logical state of the root-plus-extension chain
2. infer inherited publish policy from the root artifact set
3. run normal backup output against the reconstructed latest files
4. write a fresh standalone V1 backup to a separate output dir

The original root and extension dirs are left untouched.

## Implementation Notes

Notable properties of the current implementation:

1. Chunking is content-defined and profile-driven.
   The default extension chunker uses the full locked chain profile instead of fixed-size slicing.

2. Inspect preview numbers are execution-grade.
   `api inspect extend` derives `chunk_reuse` and `estimated_extension_bytes` from the same
   extension assembly and encryption path used by execution.

3. Chunk storage is adaptive per chunk.
   The builder emits `gzip` chunk records only when compression is smaller than raw and still
   passes extension-envelope validation; otherwise it emits `raw`.

4. Staged publish is fail closed for required shard media.
   Promotion re-scans and verifies required passphrase and signing-key shard PDFs before the final
   rename.

5. Extension AUTH is root-authorized, not just ciphertext-bound.
   Extension publish, recover, compact, and inspect now require a valid extension AUTH payload and,
   when the root is available, require its signing key to match root-derived authority.

6. Extension coverage includes end-to-end render/recover flows.
   The repo now includes integration coverage for multi-extension recovery and compacted-root parity
   in addition to the targeted unit suite.

## Practical Interpretation

What the feature is today:

- a functional append-only generation chain on top of existing backups
- explicit-scope only
- no delete support
- sealed roots blocked
- deterministic lineage metadata
- dedupe by content-defined chunk hash
- latest-state recovery and explicit compaction implemented

What it is not today:

- a delete/rename-capable sync system
- a passphrase-rotation workflow
