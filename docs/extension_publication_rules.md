# Ethernity v1.2 extension publication rules

**Status:** Normative for Ethernity v1.2.0.

This document defines the one supported way to append, publish, validate, recover, and rebuild an
Ethernity extension chain. The [core format specification](format.md) remains authoritative for
serialized bytes, cryptographic bindings, ancestry, and replay.

The key words "MUST", "MUST NOT", "REQUIRED", "SHOULD", "SHOULD NOT", "RECOMMENDED", "MAY",
and "OPTIONAL" are interpreted as described by BCP 14 when they appear in capitals.

Extension documents identify themselves through document format version 2 and extension header
schema version 1. The product release number is not serialized.

## 1) Supported operations

The product exposes four distinct operations:

- **Add Files** authenticates supplied backup documents and writes one add-or-replace extension
  package to a separate destination.
- **Restore** imports root and extension documents and recovers a selected authenticated version.
- **Replace Recovery Docs** creates new passphrase or signing-key recovery sheets for a selected
  authenticated chain, with every new sheet bound to that chain's root.
- **Rebuild** converts a supplied authenticated chain into a new standalone published backup.

Add Files, Restore, and Rebuild MUST derive chain identity from the supplied authenticated
documents. PDFs, scanned pages, QR payloads, and explicitly supplied fallback text are equivalent
sources of document content. Add Files MUST accept a complete authenticated collection with the
required root signing key regardless of filenames, directory layout, or whether the documents are
scanned or read from disk. It MUST NOT require a prior Restore or Rebuild operation.

Add Files changes only selected paths. A selected path already in the current file set is replaced;
a new path is added; an omitted path remains. Deletion and true rename require a new backup.

Every accepted update MUST leave a file set that Rebuild can encode as a valid standalone backup.
Assessment and execution MUST use the shared standalone preparation from Section 19.4 of
the core specification, including automatic payload compression, manifest metadata, encryption
overhead, and all standalone bounds. The 1 MiB ciphertext ceiling is unchanged. A failed check MUST
block publication and leave the existing backup unchanged. Readers MUST still recover earlier
oversized chains within the recovery bounds; a replacing update MAY reduce such a state until it
fits. File path ancestor conflicts, such as files `a` and `a/b`, MUST also block publication.

## 2) Source documents and chain validation

Add Files MUST treat its sources as read-only documents and require a separate output destination.
Before assessment, it MUST validate:

- the root MAIN ciphertext and AUTH binding;
- the root signing public key derived from the authenticated root manifest;
- every supplied extension AUTH binding and signature made with the root signing key;
- sequential extension indexes, root hash, parent hash, and complete ancestry;
- required file entries, chunk identities, references, and size and count limits; and
- successful replay of one authenticated file set.

The ciphertext hash, verified AUTH, and decrypted extension header establish identity and order.
Filenames, folder names, scan times, and directory order MUST NOT establish chain identity,
extension indexes, ancestry, or update eligibility. Source folders need not be writable.

Publication MUST use the same authenticated input snapshot that was assessed. It MUST NOT infer a
newer head from a source folder or require a persistent source-chain lock. Independent updates from
the same authenticated head can create valid forks; Section 9 defines the freshness requirement.

## 3) Extension output package

Each extension publication MUST contain exactly two regular PDF documents. The recommended
filenames identify their roles, authenticated extension index, and ciphertext document ID:

```text
qr_document-<index>-<doc_id>.pdf
recovery_document-<index>-<doc_id>.pdf
```

`<index>` is the authenticated extension index, displayed with a leading zero for indexes 1 through
9. `<doc_id>` is the lowercase 16-hex document ID of the extension ciphertext. These filenames are
output conventions. Users MAY rename, move, copy, or scan the documents without changing their
identity or eligibility as later inputs. No numbered directory hierarchy is required.

The roles are:

- `qr_document-*`: machine-readable MAIN and AUTH transport; and
- `recovery_document-*`: exact text fallback for the same MAIN and AUTH.

There is no extension AUTH file, extension recovery-kit file, extension kit-index file, extension
passphrase shard, or extension signing-key shard. A render style MUST NOT add, remove, rename, or
condition the document roles. Style capabilities may affect presentation only.

Private sibling staging directories use the reserved `.staging-*` namespace and are unpublished.
Folder import and discovery MUST ignore them. Filesystem input checks, including symlink checks
and size and count limits, protect input parsing; they MUST NOT require a backup publication layout.

## 4) Extension unlock and recovery sheets

Every extension uses the root backup passphrase and signing key. Add Files MAY unlock the
root with the passphrase or with enough authenticated root recovery sheets. It MUST NOT expose an
extension unlock policy or implement recovery-sheet generation.

The extension recovery document contains MAIN/AUTH fallback text and guidance. It MUST NOT contain
the plaintext passphrase or private signing key.

Replace Recovery Docs creates replacement sheets. Whether its selected target is the root or an
authenticated extension head, every emitted sheet MUST bind to the root's `doc_hash` and root
signing public key. The operation MUST authenticate and replay the complete selected prefix before
creating the new sheets. Selection establishes the checked version; it does not change their
binding target.

Root-bound replacement passphrase sheets MUST unlock the root and every recoverable prefix of
that chain. Losing a later extension MUST NOT prevent those sheets from unlocking an intact root
or older prefix. Signing-key sheets reconstruct the same root signing key. Sheets do not
pin freshness; independently recorded head hashes do that separately. Replacing a
sheet set with unchanged credentials does not revoke previous sets, which MUST NOT be mixed with
the new set during reconstruction. Users SHOULD test the new root-bound quorum before retiring
the old sheets.

Compatible replacement sheets MAY preserve an existing root-bound shard set and its `set_id`.
They MUST NOT reuse a head-bound set under the root identity. A user replacing an earlier
head-bound set MUST create a complete new root-bound set instead. Readers MAY continue to use
existing head-bound sheets only when their matching MAIN ciphertext is available and all original
binding rules pass; they do not gain root-only recovery coverage retroactively.

Add Files MAY offer recovery-sheet creation immediately after publication. It MUST invoke
Replace Recovery Docs for the newly authenticated head rather than generate sheets in the extension
operation. These sheets MUST be written outside the extension output package. A sheet-generation
failure MUST report that the extension is already published and MUST NOT invite the user to repeat
Add Files.

## 5) Document and fallback validation

Before publication, the publisher MUST scan both staged documents and validate their exact
content:

- the QR document MUST reconstruct the expected extension ciphertext and required AUTH;
- the recovery document QR and designated fallback sections MUST represent the same ciphertext and
  AUTH.

Source validation MUST authenticate the imported MAIN, AUTH, and any recovery-sheet payloads used
for unlocking. It MUST NOT require named source PDFs or companion fallback documents
merely because they were generated at creation time. Duplicate representations of a source
document are optional.

A recovery document has exactly two ordered designated sections:

```text
Auth Frame
<fallback text for exactly one AUTH frame>
Main Frame
<fallback text for exactly one MAIN frame with INDEX = 0 and TOTAL = 1>
```

Validation MUST fail for missing, malformed, extra, reordered, or mismatched designated sections.
Extractable PDF text confirms byte agreement with the authenticated payloads; it does not establish
visual legibility or constitute a signed publication inventory.

Manual fallback text MAY be accepted through an explicit text input. A recovery reader
MUST NOT scrape arbitrary PDF or image text and use it as chain input.

## 6) Chunking and replay

New v1.2 extension chains MUST use FastCDC algorithm 1. The exact algorithm, parameter bounds, and
validation rules are defined in [format.md](format.md). Applications MAY expose the minimum,
target, and maximum chunk sizes as advanced settings before the first extension is created. The
first extension authenticates and locks those sizes; every later extension in that chain MUST use
them. Changing local settings MUST NOT change an existing chain. Different sizes require rebuilding
or creating a new standalone backup and then starting a new chain.

A chain accepted as valid MUST be reconstructed from the same authenticated documents, ancestry,
chunk definitions, and size and count limits used during validation. Validation and reconstruction
MUST NOT follow separate rules that can disagree.

Chunk IDs are SHA-256 identities over decoded chunk bytes. Replay MUST fail closed on conflicting
bytes, mismatched chunk boundaries, unresolved references, invalid size/hash claims, size or count
limit violations, duplicate authenticated indexes, or divergent ancestry.

## 7) Reusable offline browser recovery kit

The offline browser recovery kit is reusable across backups. It is generated independently of any
backup and uses this embedded metadata:

```json
{
  "capability": "ethernity-unanchored-rescue",
  "version": 1,
  "supported_extension_envelope_versions": [2],
  "supported_extension_schema_versions": [1]
}
```

A separately trusted full extension-head hash can establish root identity, signing
public key, and selected-head guarantees after complete authenticated replay: the extension commits
to its root hash, and that unsealed root commits to its signing seed. A trusted full standalone-root
hash pins root identity and, when unsealed, its seed-derived signing public key. For sealed standalone
roots, it does not also pin the AUTH signing public key without a separately trusted signing-key
fingerprint.

Without an independently trusted matching fingerprint, recovery establishes only internal
consistency. Even a matching trusted record establishes the recorded version without guaranteeing
that no later offline update exists.

## 8) Atomic publication

Extension publication MUST leave source documents unchanged and MUST NOT overwrite an existing
destination. It follows this sequence:

1. create a private same-filesystem `.staging-*` sibling of the chosen destination;
2. render both required documents into it;
3. validate the exact file inventory and contents and snapshot names, sizes, and hashes;
4. verify that the output matches the reviewed authenticated input snapshot and expected next
   index, and revalidate the staging identity, snapshot, and absent destination;
5. `fsync` every staged regular file and the staging directory;
6. atomically rename the staging directory to the destination; and
7. `fsync` the destination's parent directory where the platform exposes directory flushing.

There is no transaction journal, repair command, quarantine, or resume protocol. A failed process
MUST NOT leave a partially published destination. Abandoned `.staging-*` directories remain
outside the chain and may be removed only after the user has established that no publisher is
using them.

Layout diagnostic files are optional and remain outside the extension output package. Diagnostic
failure after publication MUST NOT roll back a successfully published extension.

## 9) Selected versions and freshness

Recovery may select root, an authenticated extension index, an authenticated extension `doc_hash`,
or the latest validated head among supplied documents.

Latest recovery and Add Files MUST have one explicit freshness basis:

- a manually entered expected head hash; or
- an explicit acknowledgement that freshness is unknown.

The acknowledgement means only "latest among supplied documents." It does not prove that a newer
offline copy does not exist. It permits an update from that supplied head without claiming global
freshness. A pinned target MUST fail if it cannot be reconstructed,
authenticated, and replayed exactly.

Recovery status MUST distinguish internal consistency from verification against an independently
trusted full fingerprint. It MUST report the guarantees actually established, including
the sealed-root signing-key distinction in Section 7.

## 10) Rebuild

Rebuild MUST authenticate and replay the selected chain, then write the resulting file set as
a new standalone backup using document format version 1 in a separate directory. It MUST preserve
the source passphrase, sealed state, and, when unsealed, the root signing seed. It leaves source
documents unchanged.

For a sealed source, the manifest contains no signing seed and Rebuild does not accept signing-key
recovery inputs to preserve that key. It MUST generate a new signing key for the new sealed root.
The new AUTH payload MUST identify that new signing public key. This does not change
the source passphrase or revoke the old signing key.

Rebuild MUST use the same automatic payload compression and standalone preparation used by
Add Files rebuildability checks. It MUST NOT inherit a raw-only payload preference that could
invalidate the capacity guarantee. An earlier oversized chain MAY fail standalone preparation,
but that failure MUST NOT prevent recovery of its files.

The rebuilt ciphertext has a new identity. Rebuild MUST create fresh recovery sheets bound to
that new root. Before publication, it MUST validate the new MAIN/AUTH, every newly generated
recovery-sheet payload, and a threshold quorum from each new sheet set. A passphrase quorum MUST
unlock the new ciphertext; a signing-key quorum MUST reconstruct its signing key. Creation of an
ordinary standalone backup MUST perform the same document and recovery-sheet validation.

Before retiring source documents, users SHOULD restore the rebuilt backup with its new sheets and
record its full fingerprint separately if they use expected-version checks. The old fingerprint
will not match the rebuilt root. This does not require a filesystem registry or a signed ancestry
record.

Rebuild output uses private sibling staging, file and directory flushing, and same-filesystem atomic
rename. Like Add Files, it uses an authenticated input snapshot and MUST NOT require a specific
source folder layout or a source-chain lock.

Rebuild preserves the passphrase and does not revoke old credentials. It also preserves the signing
key for unsealed sources; sealed sources receive the new signing key described above.
Intentional passphrase or unsealed signing-key rotation, deletion, true rename, or compromise
recovery requires a new backup and retirement of the superseded documents.
