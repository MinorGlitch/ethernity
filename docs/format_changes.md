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

## 2026-04-09 - Add extension-envelope chain, compaction, and recovery profile

- Type: feature/profile
- Normative spec updated: yes
- Sections changed: 2, 3, 7, 12, 19, 20, 21
- Compatibility:
  - Old decoders reading new artifacts: no for extension envelopes and extension-chain exports;
    Version 1-only decoders reject outer envelope version 2 and do not understand extension-chain
    publication or replay.
  - New decoders reading old artifacts: yes for Version 1 root backups and existing shard/AUTH
    payloads; no previous shipped Version 2 extension artifacts existed on the release base.
- Version/profile bump required: yes (the format now defines extension envelopes with outer
  envelope `VERSION = 2`, authenticated chain replay, selected recovery, minting, and compaction).
- Implementation refs:
  - `src/ethernity/formats/extension_envelope.py`
  - `src/ethernity/formats/extension_chunking.py`
  - `src/ethernity/extensions/build.py`
  - `src/ethernity/extensions/chain.py`
  - `src/ethernity/extensions/discovery.py`
  - `src/ethernity/extensions/published.py`
  - `src/ethernity/extensions/recovery.py`
  - `src/ethernity/extensions/staging.py`
  - `src/ethernity/cli/shared/io/inputs.py`
  - `src/ethernity/cli/shared/root_shard_policy.py`
  - `src/ethernity/cli/features/extend/`
  - `src/ethernity/cli/features/recover/`
  - `src/ethernity/cli/features/mint/`
  - `src/ethernity/cli/features/compact/`
  - `kit/app/extension_envelope.js`
  - `kit/app/extension_recovery.js`
- Test refs:
  - `tests/unit/test_extension_envelope.py`
  - `tests/unit/test_extension_build.py`
  - `tests/unit/test_extension_chain.py`
  - `tests/unit/test_extension_discovery.py`
  - `tests/unit/test_extension_published.py`
  - `tests/unit/test_extension_staging.py`
  - `tests/unit/test_extend_service.py`
  - `tests/unit/test_extend_inspection.py`
  - `tests/unit/test_recover_chain.py`
  - `tests/unit/test_compact_service.py`
  - `tests/unit/test_input_files.py`
  - `tests/integration/test_integration_extensions.py`
  - `tests/e2e/test_end_to_end_v1_2_extension_golden.py`
  - `kit/tests/extension_recovery.test.mjs`
  - `kit/tests/v1_2_extension_frozen_e2e.test.mjs`
- In-branch profile decisions consolidated into this release entry:
  - Root backups remain standalone Version 1 envelopes; extension documents use outer envelope
    Version 2 and carry encrypted header/body content separately from the root.
  - Extension AUTH is transported beside the ciphertext, must bind to the extension `doc_hash`,
    and must be signed by the root-derived signing authority for authenticated replay.
  - Extension headers carry sequential index, root hash, parent hash, timestamp, chunking profile,
    and input provenance; unknown header/body keys are rejected for Version 2.
  - Extension file recipes are complete replacements for listed paths only. Deletes, renames, and
    tombstones are unsupported; omitted paths inherit their previous logical state.
  - Algorithm 1 FastCDC-style chunking is locked by the first validated extension and enforced for
    extension recipes and virtual root chunk replay.
  - Inline chunks must be referenced by files in the same envelope and must be newly introduced
    relative to virtual root chunks and earlier extensions.
  - Latest reconstructed state is bounded by `MAX_MANIFEST_FILES` and
    `MAX_DECOMPRESSED_PAYLOAD_BYTES`, and synthetic replay manifests use
    `input_origin = "directory"` with `input_roots = ["reconstructed-state"]`.
  - Content-import recovery identifies roots and extensions from recovered ciphertext, AUTH, and
    decrypted headers, not from filenames or directory order.
  - Chain IDs are deterministic metadata derived from the authenticated root document hash with
    `CHAIN_ID_PERSONALIZATION`; they are not serialized authority and caller-supplied `chain_id`
    values must not be trusted as chain membership evidence.
  - Published export trees and append workflows distinguish recovery-valid carrier sets from
    append-valid canonical layouts; scan-mode append emits loose extension bundles unless the full
    canonical prefix is present.
  - Recursive backup-export scans exclude unpublished `extensions/.staging-*` workspaces and reject
    extension-like stale top-level entries under `extensions/`.
  - Root-only and selected-prefix recovery are explicit selection modes. Default recovery replays
    the latest supplied authenticated extension and reports freshness as supplied-carriers-only.
  - Extension recovery documents are human fallback documents. They are validated for append
    readiness but are not scraped as authoritative content-import carriers.
  - Extension publish and mint paths fail closed when carriers, shard sets, chain ancestry, or
    authenticated replay cannot be validated.
  - Compaction shard policy inheritance is content-first and authenticated. Filename prefixes and
    unsigned shard metadata cannot select checkpoint policy; compaction preserves root shard policy,
    sealed/unsealed state, and any unsealed root signing seed without mutating the original carriers.
- Related branch hardening consolidated with this release entry:
  - Selected input bounds are preflighted before reading so oversized file counts, source bytes,
    symlinks, and non-regular inputs cannot bypass existing resource limits.
- Security impact:
  - Adds append-only authenticated extension replay while preserving Version 1 root compatibility.
  - Prevents unsigned or root-authority-mismatched extension replay in the shipped CLI/API profile.
  - Keeps chain membership tied to ciphertext hashes, verified AUTH, and decrypted ancestry rather
    than filesystem labels or stale export-tree layout.
  - Makes publication atomic through staged artifacts, carrier validation, and chain-head
    revalidation before promotion.

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
