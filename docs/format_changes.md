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
