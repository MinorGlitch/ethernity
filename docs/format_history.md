# Format compatibility history

This page records compatibility-relevant differences between Ethernity releases. It is not a
development diary. A version heading without a date is frozen for that release but not yet tagged.
Git history records the order in which the work was developed.

The [core format specification](format.md) defines encoded bytes and recovery rules. The
[extension publication rules](extension_publication_rules.md) define how v1.2 extension chains
are published, recovered, and rebuilt.

## Update policy

For each compatibility-relevant change:

1. Update the applicable normative document.
2. During development, record the change under **Next release**, including old-reader and
   new-reader behavior.
3. Do not copy source-file lists, test lists, or in-branch chronology into this page.
4. At release freeze, replace **Next release** with the product version. After tagging, append the
   tag date to that version heading.

Editorial changes with no format or decoder impact do not belong here.

## v1.2.0

### Extension document v2 and publication rules

- Type: wire format and required product behavior
- Affected rules: core extension format, authenticated chain selection and replay, and extension
  publication and recovery
- Compatibility:
  - Older readers cannot decode extension document v2 or operate an extension chain.
  - v1.2 readers continue to decode standalone backup document v1, AUTH payload v1, shard payloads v1
    and v2, and existing QR/fallback transports.
  - No extension document v2 was part of a released Ethernity version before v1.2.
- Versioning: extension documents use document format version 2 and header schema version 1. Root
  backups remain standalone backup document version 1.
- Summary:
  - Adds authenticated, append-only add-or-replace extension chains with parent hashes,
    content-defined chunking, replay, resource bounds, and offline fork detection.
  - Adds recovery and updates that derive document identity and order from ciphertext hashes,
    AUTH, and decrypted headers rather than filenames or directory order. Original PDFs, scans,
    and explicit fallback text can supply the same chain without rebuilding it first.
  - Adds v1.2 rules for two required extension documents in a separate output package, inherited
    the root passphrase used to decrypt extensions, selected recovery, replacement recovery sheets,
    reusable browser kits, rebuilding, and staged atomic publication.
  - Requires every newly published update to fit a standalone backup, checked through shared
    encoding with automatic compression and all standalone limits. Recovery remains compatible
    with previously created oversized states within the existing chain limits.
  - Binds newly generated replacement recovery sheets to the root for recovery of any intact
    prefix. Creation and Rebuild validate the published backup and a quorum of each recovery-sheet set.
  - Rebuild preserves the passphrase and sealed state, and preserves the signing key for
    unsealed sources. Sealed-source Rebuild generates a new signing key because the source
    manifest contains no seed; its new AUTH identifies the new key.
  - Defines bounded, authenticated FastCDC algorithm 1 parameters and cross-language conformance
    vectors for the default settings.
- Security impact: each extension belongs to the chain identified by its authenticated root hash,
  parent hash, and root-key signature. Publication uses the reviewed authenticated input snapshot,
  leaves sources unchanged, rejects existing destinations, flushes every staged regular file,
  and uses directory flushing where the platform exposes it. Add Files and browser recovery require
  a manually entered expected head or an explicit freshness-unknown acknowledgement.
  A separately trusted matching full extension-head fingerprint establishes the expected
  head, root identity, and signing key after authenticated replay. A trusted standalone-root
  hash also pins root identity and the unsealed signing key, but a sealed root needs a trusted
  signing-key fingerprint to verify its AUTH signing key. Sets without an independently
  trusted record are reported as internally consistent.
  Untrusted PDF/image parsing and age decryption now run in disposable workers with resource limits.
  Public scrypt stanzas are checked against per-stanza and cumulative KDF work limits. Higher work
  requires explicit approval. The guided app offers a retry with estimated memory only after a
  normal-limit failure; hard limits still reject excessive parameters.
- Verification: the frozen v1.2 extension golden suite covers Python and browser recovery.

### Core interoperability clarifications

- Type: decoder and cryptographic validation
- Affected rules: signing-key binding, AUTH payload count, Shamir field representation, payload
  length, path syntax, and fallback text decoding
- Compatibility:
  - Document bytes are unchanged; older readers can still read all generated documents.
  - The Shamir rules freeze the existing GF(2^128) big-endian representation and direct index
    mapping; existing shard bytes are unchanged.
  - v1.2 readers deterministically remove one dotted rendered line label, collapse identical AUTH
    payload copies, reject conflicting AUTH payloads, require exact raw payload length, and enforce
    the existing POSIX path restrictions.
  - Readers reject a standalone or replayed file set in which one normalized file path is an
    ancestor of another. Such sets cannot be restored as a directory tree; older readers may
    have accepted them before failing during export. Encoders do not emit them.
  - Authenticated recovery now specifies the already-enforced requirement that root AUTH, the
    embedded or reconstructed signing seed, shards, and extension AUTH identify the same public key.
- Versioning: no format-version bump; these rules make reader behavior unambiguous without changing
  serialized fields.
- Security impact: readers fail closed on signing-key substitution, ambiguous AUTH selection,
  trailing raw payload bytes, and incompatible path interpretation.

## v1.1.0 (2026-03-29)

### Signed shard-set identifiers

- Type: wire format
- Affected rules: shard payload and Shamir reconstruction
- Compatibility:
  - Version-1-only shard readers reject newly encoded shard payload v2.
  - Current readers accept shard payload v1, but version-1 sets cannot guarantee detection of
    inputs containing exactly the required threshold of shares from distinct sets.
- Versioning: new shard payloads use version 2 and include a signed 16-byte `set_id`.
- Security impact: readers can reject mixed exact-threshold shard sets before reconstruction or
  replacement creation.

## v1.0.0 (2026-03-04)

### Initial public format baseline

- Type: compatibility baseline
- Released formats: standalone backup document v1, manifest v1, frame v1, AUTH payload v1, shard
  payload v1, QR transport, fallback text, age encryption, BIP-39 passphrases, and Shamir recovery
- Compatibility: this release establishes the baseline against which later entries are described.
