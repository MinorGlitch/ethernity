# Format Changes

This document tracks format evolution over time.

`docs/format.md` remains the single normative specification. This file is a change ledger and
release-facing summary, not a replacement for normative text.

## Update Policy

For any format-related addition or change:

1. Update `docs/format.md` when wire format, validation behavior, or interoperability requirements
   change.
2. Update `docs/format_notes.md` only for rationale and operational guidance (non-normative).
3. Add an entry here describing the delta and compatibility impact.
4. Add or update tests that cover must-pass and must-reject behavior for the change.

## Entry Template

Use this template for each change entry:

```md
## YYYY-MM-DD - <short change title>

- Type: <wire-format | validation | editorial | notes-only>
- Normative spec updated: <yes/no>
- Sections changed: <for example: 5, 10, 17, 18.3>
- Compatibility:
  - Old decoders reading new artifacts: <yes/no/partial + short note>
  - New decoders reading old artifacts: <yes/no/partial + short note>
- Version/profile bump required: <yes/no + rationale>
- Implementation refs:
  - <path>
- Test refs:
  - <path>
- Security impact:
  - <none or short note>
```

## Versioning Guidance

- Bump version/profile when an older decoder could misinterpret bytes, accept invalid data, or fail
  security-critical validation under the new behavior.
- No bump is typically needed for editorial clarifications, rationale-only notes, or strict fail-
  closed checks that preserve safe rejection semantics.

## Entries

## 2026-05-11 - Clarify extension recovery documents as human fallback only

- Type: validation
- Normative spec updated: yes
- Sections changed: 19, 21
- Compatibility:
  - Old decoders reading new artifacts: unchanged
  - New decoders reading old artifacts: unchanged for machine-readable QR carriers; extension
    recovery-document PDF text is no longer treated as a content-import carrier
- Version/profile bump required: no (wire bytes and authenticated QR carrier semantics are
  unchanged; this removes an implementation-level PDF text scraping dependency)
- Implementation refs:
  - `src/ethernity/extensions/discovery.py`
  - `src/ethernity/cli/features/extend/planning.py`
  - `src/ethernity/cli/features/extend/main_carrier_validation.py`
- Test refs:
  - `tests/unit/test_extend_service.py`
  - `tests/unit/test_extend_inspection.py`
  - `tests/integration/test_integration_extensions.py`
- Security impact:
  - Keeps extension chain replay tied to authenticated machine-readable carriers and prevents PDF
    display text extraction from becoming a recovery trust boundary.

## 2026-05-09 - Validate extension carrier copies and mint replay targets

- Type: validation
- Normative spec updated: yes
- Sections changed: 20, 21
- Compatibility:
  - Old decoders reading new artifacts: unchanged
  - New decoders reading old artifacts: partial (published extension sets with a broken redundant
    recovery-document render contract are rejected at publish time, and mint refuses authenticated
    extension heads that cannot replay)
- Version/profile bump required: no (wire bytes are unchanged; this aligns publish and mint
  trust decisions with existing authenticated replay invariants)
- Implementation refs:
  - `src/ethernity/cli/features/extend/main_carrier_validation.py`
  - `src/ethernity/cli/features/mint/workflow.py`
- Test refs:
  - `tests/unit/test_extend_service.py`
  - `tests/unit/test_mint_inspection.py`
- Security impact:
  - Prevents promotion of QR carriers that do not authenticate to the planned extension ciphertext
    and prevents minting shard documents bound to extension heads that fail replay.

## 2026-05-09 - Enforce newly introduced extension chunk records across the chain

- Type: validation
- Normative spec updated: yes
- Sections changed: 19.5
- Compatibility:
  - Old decoders reading new artifacts: unchanged
  - New decoders reading old artifacts: partial (extension envelopes that repeat a root or earlier
    extension chunk as a current inline `chunks` record are rejected)
- Version/profile bump required: no (the Version 2 extension profile already models `chunks` as
  newly introduced records; this is a strict fail-closed enforcement of that invariant)
- Implementation refs:
  - `src/ethernity/extensions/chain.py`
  - `src/ethernity/cli/features/extend/planning.py`
  - `src/ethernity/cli/features/extend/prepare.py`
- Test refs:
  - `tests/unit/test_extension_chain.py`
  - `tests/unit/test_extend_service.py`
- Security impact:
  - Keeps extension replay deterministic and prevents redundant inline chunk records from being
    accepted as valid chain state.

## 2026-05-09 - Preserve compact passphrase shard policy from external unlock shards

- Type: validation
- Normative spec updated: yes
- Sections changed: 21
- Compatibility:
  - Old decoders reading new artifacts: unchanged
  - New decoders reading old artifacts: yes (compacted checkpoints remain standalone Version 1
    backups, now with preserved passphrase shard documents when source unlock used shards)
- Version/profile bump required: no (the wire format is unchanged; this prevents a policy
  downgrade during compaction)
- Implementation refs:
  - `src/ethernity/cli/features/compact/service.py`
- Test refs:
  - `tests/unit/test_compact_service.py`
- Security impact:
  - Prevents compact from exposing the plaintext passphrase in the checkpoint recovery document
    when the source was unlocked with separately stored passphrase shard carriers.

## 2026-05-09 - Exclude unpublished extension staging from recursive scans

- Type: validation
- Normative spec updated: yes
- Sections changed: 20
- Compatibility:
  - Old decoders reading new artifacts: unchanged
  - New decoders reading old artifacts: yes (published carriers and explicitly supplied carrier
    files remain valid scan inputs)
- Version/profile bump required: no (the wire format is unchanged; this tightens recursive
  directory import selection for implementation-private staging workspaces)
- Implementation refs:
  - `src/ethernity/qr/scan.py`
- Test refs:
  - `tests/unit/test_qr_scan_more.py`
- Security impact:
  - Prevents aborted or unpromoted extension staging artifacts from silently becoming supplied
    recovery material when scanning a backup root directory.

## 2026-05-08 - Clarify extension head freshness scope

- Type: editorial
- Normative spec updated: yes
- Sections changed: 20, 21
- Compatibility:
  - Old decoders reading new artifacts: unchanged
  - New decoders reading old artifacts: unchanged
- Version/profile bump required: no (this clarifies the authenticated recovery guarantee without
  changing envelope bytes or replay validation)
- Implementation refs:
  - `src/ethernity/cli/features/recover/chain.py`
  - `src/ethernity/cli/features/compact/service.py`
  - `src/ethernity/render/copy_catalog.py`
  - `tooling/document_inspector_app/analysis.py`
- Test refs:
  - `tests/unit/test_extend_service.py`
  - `tests/unit/test_compact_service.py`
  - `tests/unit/test_cli_api.py`
  - `tests/unit/test_document_inspector_tool.py`
  - `tests/integration/test_integration_extensions.py`
- Security impact:
  - Prevents release docs and user-facing errors from implying absolute proof that no later
    extension exists without an external freshness source

## 2026-05-08 - Preserve extension input root label whitespace

- Type: validation
- Normative spec updated: yes
- Sections changed: 19.2
- Compatibility:
  - Old decoders reading new artifacts: partial (older builds may trim extension `input_roots`
    labels with leading or trailing whitespace when displaying provenance metadata)
  - New decoders reading old artifacts: yes (already-trimmed labels remain valid)
- Version/profile bump required: no (this clarifies and preserves authenticated provenance
  metadata without changing extension envelope structure or replay security)
- Implementation refs:
  - `src/ethernity/formats/extension_envelope.py`
- Test refs:
  - `tests/unit/test_extension_envelope.py`
- Security impact:
  - none

## 2026-05-08 - Enforce canonical extension chunk recipes at build and replay boundaries

- Type: validation
- Normative spec updated: no
- Sections changed: none (enforces existing Sections 19.3.1 and 19.3.1.1 requirements)
- Compatibility:
  - Old decoders reading new artifacts: unchanged (the wire format is unchanged)
  - New decoders reading old artifacts: partial (extension file recipes whose chunk references do
    not match the locked content-defined chunking profile are now rejected)
- Version/profile bump required: no (this is a strict fail-closed decoder check for the existing
  Version 2 extension profile)
- Implementation refs:
  - `src/ethernity/formats/extension_chunking.py`
  - `src/ethernity/formats/extension_envelope.py`
  - `src/ethernity/extensions/chunking.py`
  - `src/ethernity/extensions/build.py`
  - `src/ethernity/extensions/chain.py`
- Test refs:
  - `tests/unit/test_extension_build.py`
  - `tests/unit/test_extension_envelope.py`
  - `tests/unit/test_extension_chain.py`
- Security impact:
  - Rejects authenticated-but-non-canonical extension recipes that reconstruct the correct bytes
    through invalid chunk boundaries, keeping replay deterministic across implementations.

## 2026-05-08 - Define reconstructed extension-state provenance

- Type: validation
- Normative spec updated: yes
- Sections changed: 19.5
- Compatibility:
  - Old decoders reading new artifacts: unchanged (the wire format is unchanged)
  - New decoders reading old artifacts: changed metadata semantics for replayed extension states;
    synthetic recovered/compacted manifests now identify themselves as reconstructed state instead
    of borrowing root or latest-extension source scope
- Version/profile bump required: no (this changes synthetic manifest metadata produced during
  replay/compaction, not the encoded extension document profile)
- Implementation refs:
  - `src/ethernity/cli/features/recover/chain.py`
  - `src/ethernity/cli/features/compact/service.py`
- Test refs:
  - `tests/unit/test_recover_chain.py`
  - `tests/unit/test_compact_service.py`
- Security impact:
  - Prevents compacted full-state backups from presenting a misleading narrow provenance inherited
    from the final extension document.

## 2026-05-08 - Clarify chain-global root chunk reuse

- Type: clarification
- Normative spec updated: yes
- Sections changed: 19.5
- Compatibility:
  - Old decoders reading new artifacts: unchanged (the wire format is unchanged)
  - New decoders reading old artifacts: unchanged (this documents existing replay semantics)
- Version/profile bump required: no (this clarifies chunk-resolution scope without changing encoded
  data or replay behavior)
- Implementation refs:
  - `src/ethernity/extensions/chain.py`
  - `src/ethernity/cli/features/recover/chain.py`
- Test refs:
  - `tests/unit/test_extension_chain.py`
- Security impact:
  - Makes clear that path replacement does not imply erasure of content-addressed root payload
    chunks that remain physically present in the root backup.

## 2026-05-08 - Remove public unsigned recovery flags

- Type: validation
- Normative spec updated: yes
- Sections changed: 19.4; CLI/API documentation
- Compatibility:
  - Old decoders reading new artifacts: unchanged (the wire format is unchanged)
  - New decoders reading old artifacts: unchanged for authenticated recovery; public
    unauthenticated recovery flags are rejected by the CLI/API
- Version/profile bump required: no (this is a strict fail-closed command policy and does not alter
  encoded data)
- Implementation refs:
  - `src/ethernity/cli/features/recover/chain.py`
  - `src/ethernity/cli/features/recover/command.py`
  - `src/ethernity/cli/features/api/command.py`
- Test refs:
  - `tests/unit/test_recover_chain.py`
- Security impact:
  - Prevents unsigned recovery from being exposed as a shipped user-facing path. Extension replay
    remains authenticated-only.

## 2026-05-08 - Cap latest extension state file count

- Type: validation
- Normative spec updated: yes
- Sections changed: 19.5
- Compatibility:
  - Old decoders reading new artifacts: unchanged (the wire format is unchanged)
  - New decoders reading old artifacts: partial (chains whose replayed latest logical state exceeds
    `MAX_MANIFEST_FILES` are now rejected)
- Version/profile bump required: no (this is a strict fail-closed replay/build invariant that keeps
  extension chains representable as Version 1 compaction outputs)
- Implementation refs:
  - `src/ethernity/extensions/build.py`
  - `src/ethernity/extensions/chain.py`
- Test refs:
  - `tests/unit/test_extension_build.py`
  - `tests/unit/test_extension_chain.py`
- Security impact:
  - Prevents valid-looking extension chains from producing latest states that cannot be compacted
    into the bounded Version 1 manifest profile

## 2026-05-08 - Clarify extension delete semantics

- Type: editorial
- Normative spec updated: yes
- Sections changed: 19
- Compatibility:
  - Old decoders reading new artifacts: unchanged (the extension envelope wire shape and file recipe
    records are unchanged)
  - New decoders reading old artifacts: yes (the text freezes existing Version 2 behavior; no valid
    delete or tombstone records existed)
- Version/profile bump required: no (this is a normative clarification of the existing immutable
  extension model and does not alter encoded data)
- Implementation refs:
  - `src/ethernity/cli/features/extend/planning.py`
  - `src/ethernity/formats/extension_envelope.py`
- Test refs:
  - `tests/unit/test_extend_service.py`
- Security impact:
  - Avoids ambiguous erasure semantics by making previously backed content remain recoverable until
    replaced by later file content or excluded by a new root backup.

## 2026-05-08 - Specify extension FastCDC-style chunking algorithm

- Type: editorial
- Normative spec updated: yes
- Sections changed: 19
- Compatibility:
  - Old decoders reading new artifacts: unchanged (the extension envelope wire shape and stored
    chunking profile are unchanged)
  - New decoders reading old artifacts: yes (the text freezes the existing algorithm rather than
    changing accepted artifacts)
- Version/profile bump required: no (this is a normative clarification of the existing Version 2
  extension profile and does not alter encoded data)
- Implementation refs:
  - `src/ethernity/extensions/build.py`
- Test refs:
  - `tests/unit/test_extension_build.py`
- Security impact:
  - Improves independent replay conformance for virtual root chunk reuse; chunk integrity remains
    enforced by SHA-256 and authenticated extension replay.

## 2026-05-07 - Fail closed on extension trust and carrier reconstruction

- Type: validation
- Normative spec updated: yes
- Sections changed: 7, 8, 19, 20, 21
- Compatibility:
  - Old decoders reading new artifacts: unchanged (the wire shape and canonical carrier filenames
    are unchanged)
  - New decoders reading old artifacts: partial (extension directories with damaged sibling MAIN
    carriers, duplicate shard share indexes, or extensions on sealed roots are now rejected by the
    authenticated extension replay path)
- Version/profile bump required: no (the change tightens validation and preserves fail-closed
  semantics on the existing Version 2 extension profile)
- Implementation refs:
  - `src/ethernity/extensions/discovery.py`
  - `src/ethernity/extensions/staging.py`
  - `src/ethernity/formats/extension_envelope.py`
  - `src/ethernity/cli/features/extend/execution.py`
  - `src/ethernity/cli/features/extend/planning.py`
  - `src/ethernity/cli/features/recover/chain.py`
- Test refs:
  - `tests/unit/test_extension_discovery.py`
  - `tests/unit/test_extension_envelope.py`
  - `tests/unit/test_extension_staging.py`
  - `tests/unit/test_extend_service.py`
  - `tests/unit/test_recover_chain.py`
- Security impact:
  - Keeps sealed roots terminal, requires machine-readable extension carriers to independently recover, and
    prevents staged promotion from swapping a validated directory for a symlink before rename.
    Also clarifies that extension `doc_hash` target matches are provisional until authenticated
    replay succeeds, and that inspection/projection surfaces may fail closed more strictly than
    explicit rescue-mode recovery.

## 2026-04-10 - Require root-authorized extension AUTH in existing carriers

- Type: validation
- Normative spec updated: yes
- Sections changed: 19, 20
- Compatibility:
  - Old decoders reading new artifacts: partial (older extension readers that ignore or do not
    enforce extension AUTH root-authority matching can misclassify trust state)
  - New decoders reading old artifacts: partial (Version 1 root backups remain readable; extension
    directories without root-authorized AUTH are no longer accepted in authenticated mode)
- Version/profile bump required: no (the extension envelope stays outer Version 2 and the carrier
  set stays unchanged; the delta is fail-closed authentication validation on existing carriers)
- Implementation refs:
  - `src/ethernity/cli/features/extend/service.py`
  - `src/ethernity/cli/features/recover/chain.py`
  - `tooling/document_inspector_app/analysis.py`
- Test refs:
  - `tests/unit/test_extend_service.py`
  - `tests/unit/test_recover_chain.py`
  - `tests/unit/test_document_inspector_tool.py`
- Security impact:
  - Makes extension acceptance depend on AUTH signed by the root-derived authority instead of
    ciphertext integrity and lineage alone

## 2026-04-09 - Finalize the Version 2 extension schema in place

- Type: wire-format
- Normative spec updated: yes
- Sections changed: 19
- Compatibility:
  - Old decoders reading new artifacts: no (the Version 2 extension header now uses the finalized
    field set and older extension decoders expect a different header shape)
  - New decoders reading old artifacts: partial (Version 1 root backups remain readable; Version 2
    extension compatibility follows the finalized schema defined in Section 19)
- Version/profile bump required: no (standalone Version 1 root compatibility is preserved and the
  extension envelope remains outer Version 2)
- Implementation refs:
  - `src/ethernity/formats/extension_envelope.py`
  - `src/ethernity/extensions/chain.py`
  - `src/ethernity/cli/features/extend/service.py`
- Test refs:
  - `tests/unit/test_extension_envelope.py`
  - `tests/unit/test_extension_chain.py`
  - `tests/unit/test_document_inspector_tool.py`
- Security impact:
  - Moves extension authority ownership to the root backup and removes extension-embedded signing
    authority fields

## 2026-04-09 - Harden extension-envelope chunking and staged publish validation

- Type: editorial
- Normative spec updated: yes
- Sections changed: 19, 20
- Compatibility:
  - Old decoders reading new artifacts: unchanged
  - New decoders reading old artifacts: unchanged
- Version/profile bump required: no (the extension-envelope wire shape remains outer envelope
  version 2; this entry tightens implementation-aligned chunking and publish-validation
  requirements)
- Implementation refs:
  - `src/ethernity/extensions/build.py`
  - `src/ethernity/cli/features/extend/service.py`
  - `src/ethernity/cli/features/recover/chain.py`
- Test refs:
  - `tests/unit/test_extension_build.py`
  - `tests/unit/test_extend_service.py`
  - `tests/integration/test_integration_extensions.py`
- Security impact:
  - Makes staged extension promotion fail closed for shard media and aligns replay/build chunking
    behavior with the stored chain profile

## 2026-05-08 - Replace extension directory recovery with content import

- Type: wire-format recovery profile
- Normative spec updated: yes
- Sections changed: 20, 21
- Compatibility:
  - Old decoders reading new artifacts: unchanged for envelope bytes, but old recovery tools may
    require extension directories that are no longer normative
  - New decoders reading old artifacts: yes, as long as the carriers can be scanned or pasted
- Version/profile bump required: no envelope version bump; this removes filesystem layout from the
  recovery profile without changing extension-envelope bytes
- Implementation refs:
  - `src/ethernity/cli/features/recover/chain.py`
  - `src/ethernity/cli/features/recover/planning.py`
- Test refs:
  - `tests/unit/test_recover_chain.py`
  - `tests/unit/test_recover_plan_paths.py`
  - `tests/unit/test_recover_wizard.py`
- Security impact:
  - Moves recovery identity to ciphertext `doc_hash`, AUTH, and decrypted extension headers instead
    of directory names or filenames

## 2026-04-09 - Add extension-envelope chain and compaction format rules

- Type: wire-format
- Normative spec updated: yes
- Sections changed: 2, 12, 19, 20, 21
- Compatibility:
  - Old decoders reading new artifacts: no (Version 1-only decoders reject extension envelopes,
    which use outer envelope version 2, and do not understand extension-chain directories)
  - New decoders reading old artifacts: yes (standalone Version 1 backups remain readable without
    extensions)
- Version/profile bump required: yes (the format now includes extension envelopes with outer
  envelope version 2 and authenticated chain replay semantics)
- Implementation refs:
  - `src/ethernity/formats/extension_envelope.py`
  - `src/ethernity/extensions/discovery.py`
  - `src/ethernity/extensions/chain.py`
  - `src/ethernity/cli/features/recover/chain.py`
  - `src/ethernity/cli/features/compact/service.py`
- Test refs:
  - `tests/unit/test_extension_envelope.py`
  - `tests/unit/test_extension_discovery.py`
  - `tests/unit/test_extension_chain.py`
  - `tests/unit/test_recover_chain.py`
  - `tests/unit/test_compact_service.py`
- Security impact:
  - Adds authenticated ancestry validation for extension replay and makes compaction the explicit
    rebase path instead of allowing in-place chain rewriting

## 2026-03-11 - Add signed shard-set identifiers to shard payloads

- Type: wire-format
- Normative spec updated: yes
- Sections changed: 9, 15.3, 15.4
- Compatibility:
  - Old decoders reading new artifacts: no (new shard payloads use version 2 and are rejected by
    version-1-only decoders)
  - New decoders reading old artifacts: partial (legacy version 1 shards remain readable, but they
    do not carry `set_id` and therefore cannot guarantee exact-quorum mixed-set detection)
- Version/profile bump required: yes (older decoders would otherwise miss a security-critical
  shard-set consistency check)
- Implementation refs:
  - `src/ethernity/crypto/signing.py`
  - `src/ethernity/crypto/sharding.py`
  - `src/ethernity/cli/keys/recover_keys.py`
  - `src/ethernity/cli/flows/prompts.py`
- Test refs:
  - `tests/unit/test_signing.py`
  - `tests/unit/test_sharding.py`
  - `tests/unit/test_recover_keys.py`
  - `tests/unit/test_recover_shard_prompts.py`
  - `tests/unit/test_cli_flow_prompts.py`
- Security impact:
  - Prevents version 2 shard payloads from silently accepting mixed exact-threshold shard sets
    during recovery or replacement minting

## 2026-03-06 - Format change tracking structure introduced

- Type: editorial
- Normative spec updated: no
- Sections changed: none
- Compatibility:
  - Old decoders reading new artifacts: unchanged
  - New decoders reading old artifacts: unchanged
- Version/profile bump required: no (documentation process only)
- Implementation refs:
  - N/A
- Test refs:
  - N/A
- Security impact:
  - none
