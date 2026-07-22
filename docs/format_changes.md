# Format Compatibility History

This ledger records compatibility-relevant differences between Ethernity releases and finalized
release targets. It is not a development diary. A version heading without a date is frozen for that
release but not yet tagged. Git history records the order in which the work was developed.

The [core format specification](format.md) defines interoperable bytes and recovery semantics. The
[extension operations and publication profile](extension_publication_profile.md) defines the
v1.2 product rules for publishing and operating extension chains.

## Update policy

For each compatibility-relevant change:

1. Update the applicable normative document.
2. During development, record the change under **Next release**, including old-reader and
   new-reader behavior.
3. Keep implementation inventories, test inventories, and in-branch chronology out of this ledger.
4. At release freeze, replace **Next release** with the product version. After tagging, append the
   tag date to that version heading.

Editorial changes with no artifact or decoder impact do not belong here.

## v1.2.0

### Extension envelope v2 and operations profile v1

- Type: wire format and product profile
- Normative surface: core extension format, authenticated chain selection and replay, and extension
  operations/publication profile
- Compatibility:
  - Older readers cannot decode extension envelope v2 or operate an extension publication tree.
  - v1.2 readers continue to decode standalone root envelope v1, AUTH payload v1, shard payloads v1
    and v2, and existing QR/fallback transports.
  - No extension envelope v2 artifact was part of a released Ethernity version before v1.2.
- Versioning: extension documents use outer envelope version 2 and header schema version 1. Root
  backups remain standalone envelope version 1.
- Summary:
  - Adds authenticated, append-only add-or-replace extension chains with deterministic ancestry,
    content-defined chunking, replay, resource bounds, and offline fork detection.
  - Adds content-addressed recovery that derives identity and order from ciphertext, AUTH, and
    decrypted headers rather than filenames or directory order.
  - Adds a v1.2 operations profile for canonical publication, shard custody policy, selected
    recovery, replacement shard minting, compaction, chain-bound recovery kits, and journaled
    atomic publication with authenticated repair.
  - Freezes FastCDC-style algorithm 1 with cross-language conformance vectors.
- Security impact: extension membership is bound to root-authorized signatures and decrypted
  ancestry. Publication is fail-closed, serialized by one kernel-owned advisory lock, flushes every
  staged regular file, and uses directory flushing where the platform exposes it. Restart repair
  authenticates the chain and transaction snapshot before acting. Browser recovery no longer
  silently selects the latest supplied state:
  it requires a chain-bound-kit head pin, a manually entered expected head, or an explicit
  freshness-unknown acknowledgement. Only a separately stored chain-bound kit supports the
  **Matched trusted kit** identity claim; unanchored sets are reported as internally consistent.
  Untrusted PDF/image parsing and age decryption now run in disposable resource-bounded workers.
  Public scrypt stanzas are preflighted against per-stanza and cumulative KDF budgets; exceptional
  legacy work requires the explicit resource-intensive compatibility recovery operation, while
  excessive parameters remain a hard rejection.
- Conformance evidence: the frozen v1.2 extension golden suite covers Python and browser recovery.

### Core interoperability clarifications

- Type: decoder and cryptographic validation
- Normative surface: authority binding, AUTH cardinality, Shamir field representation, payload
  length, path syntax, and fallback text decoding
- Compatibility:
  - Artifact bytes are unchanged; older readers can still read all generated artifacts.
  - The Shamir rules freeze the existing GF(2^128) big-endian representation and direct index
    mapping; existing shard bytes are unchanged.
  - v1.2 readers deterministically remove one dotted rendered line label, collapse identical AUTH
    carrier copies, reject conflicting AUTH payloads, require exact raw payload length, and enforce
    the existing POSIX path restrictions.
  - Authenticated recovery now states the already-enforced equality chain from root AUTH through an
    embedded or reconstructed signing seed, shards, and extension AUTH payloads.
- Versioning: no format-version bump; these rules make existing decoder and trust boundaries
  independently implementable without changing serialized fields.
- Security impact: readers fail closed on authority substitution, ambiguous AUTH selection,
  trailing raw payload bytes, and incompatible path interpretation.

## v1.1.0 (2026-03-29)

### Signed shard-set identifiers

- Type: wire format
- Normative surface: shard payload and Shamir reconstruction
- Compatibility:
  - Version-1-only shard readers reject newly encoded shard payload v2.
  - Current readers accept legacy shard payload v1, but legacy sets cannot guarantee detection of
    mixed exact-quorum shares from distinct sets.
- Versioning: new shard payloads use version 2 and include a signed 16-byte `set_id`.
- Security impact: readers can reject mixed exact-threshold shard sets before reconstruction or
  replacement minting.

## v1.0.0 (2026-03-04)

### Initial public format baseline

- Type: compatibility baseline
- Released surface: standalone envelope v1, manifest v1, frame v1, AUTH payload v1, shard payload
  v1, QR transport, fallback text, age encryption, BIP-39 passphrases, and Shamir recovery
- Compatibility: this release establishes the baseline against which later entries are described.
