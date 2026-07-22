# Ethernity v1.2 Extension Operations and Publication Profile

**Status:** Normative release profile for Ethernity v1.2.0.

This document is normative for implementations that claim the Ethernity v1.2 extension operations
profile. It defines how an implementation imports, publishes, validates, and maintains extension
chains. The [core format specification](format.md) remains authoritative for serialized bytes,
cryptographic bindings, chain ancestry, and replay.

The key words "MUST", "MUST NOT", "REQUIRED", "SHOULD", "SHOULD NOT", "RECOMMENDED",
"NOT RECOMMENDED", "MAY", and "OPTIONAL" in this document are to be interpreted as described in
BCP 14 ([RFC 2119](https://www.rfc-editor.org/rfc/rfc2119),
[RFC 8174](https://www.rfc-editor.org/rfc/rfc8174)) when, and only when, they appear in all capitals.

The product release version is not serialized into an artifact. Extension artifacts identify
themselves through outer envelope version 2 and extension header schema version 1.

## 1) Scope

This profile defines:

- canonical root and extension export-tree validation;
- recovery-valid and append-valid carrier sets;
- canonical artifact roles and filenames;
- PDF fallback-text validation before publication and append;
- extension passphrase-shard custody policies;
- chain-bound and unanchored recovery-kit metadata;
- atomic publication, selected recovery, shard minting, and compaction.

CLI syntax, screen flow, visual layout, and template styling are not normative. Operator procedures
are documented in [Advanced workflows](advanced-workflows.md).

## 2) Carrier Import and Publication State

Core recovery is content-addressed. Filenames and directory names do not establish document
identity, chain membership, or order. The core format rules determine those properties from
recovered ciphertext, AUTH, and decrypted extension headers.

A carrier set can be:

- **recovery-valid** when it contains enough authenticated machine-readable material to reconstruct
  the selected root and extension chain;
- **append-valid** when it is recovery-valid and also satisfies the canonical publication layout,
  redundancy, and fallback-audit requirements in this profile.

Recovery MAY succeed from a recovery-valid set that is not append-valid. An implementation MUST NOT
describe a non-canonical or incomplete export tree as append-valid.

Recursive scans of a canonical backup export MUST:

- exclude `extensions/.staging-*` transaction workspaces because their contents are unpublished;
- reject extension-like non-canonical entries directly under `extensions/`, including stale names
  such as `extension-01` and extension artifact files outside an indexed directory;
- allow clearly unrelated clutter outside the canonical extension namespace to be ignored.

When a caller explicitly selects the root-only state, a recursive scan MAY ignore the contents of
published extension carriers after validating the top-level `extensions/` namespace.

An append created from printed or scanned carriers does not require the original export tree. If the
implementation cannot rehydrate the complete canonical publication prefix, it MUST publish a loose
artifact bundle outside the canonical `extensions/` namespace. It MUST NOT create a
canonical-looking indexed extension directory. The loose-bundle output root MUST be missing or
empty before publication and MUST be dedicated to that generated output. Doctor repair applies
only to transactions under a canonical backup's `extensions/` namespace. If loose publication is
interrupted before a final `extension-*` directory is promoted, an operator MAY, after confirming
that no Add Files process still owns the output, abandon the entire dedicated loose output root or
select a different empty root. Implementations MUST NOT advise surgical deletion of its lock,
journal, or staging entries. A loose root containing a promoted `extension-*` directory is
published output and MUST be preserved unless the operator intentionally retires the whole bundle.

## 3) Canonical Root Export Validation

Creating a canonical root export, or appending from one, MUST require
`recovery_document.pdf`. Its designated fallback sections MUST exact-decode to the authenticated
root AUTH frame and the single fallback MAIN frame whose `INDEX = 0`, `TOTAL = 1`, and `DATA` is the
complete root ciphertext.

Canonical root shard filenames are:

```text
shard-<doc_id>-<share_index>-of-<share_count>.pdf
signing-key-shard-<doc_id>-<share_index>-of-<share_count>.pdf
```

For every file matching that grammar, validation MUST:

- require exactly one distinct `KEY_DOCUMENT` QR frame;
- require the signed shard payload and fallback text to match the filename role, lowercase
  16-hex `doc_id`, share index and count, authenticated root `doc_hash`, and `root_sign_pub` from
  Section 7.2 of the core format specification;
- require each present passphrase or signing-key role to form one complete, internally consistent
  set with indexes `1..share_count`.

A matching-root shard under a non-canonical filename MAY be audited as an individual carrier, but
its filename does not establish set membership or completeness. Every canonical-pattern filename
remains fail-closed, including a file whose contents belong to a foreign root.

Non-PDF `KEY_DOCUMENT` carriers and unrelated or foreign-root carriers under non-canonical
filenames are outside this canonical fallback audit. This exclusion does not prevent a separate
content-import operation from accepting an otherwise valid authenticated carrier.

Root envelope v1 has no signed publication inventory. If no canonical filenames for a shard role
are present, validation cannot infer whether that role was never published or is now missing. It
MUST NOT claim completeness for an absent role. This limitation does not relax validation of any
canonical set that is present.

## 4) Canonical Extension Export Layout

An implementation appending to an existing export tree MUST validate the current published head
before it publishes the next extension.

Canonical extension directory names use the decimal extension index:

- two digits for indexes `1..99` (`01`, `02`, ..., `99`);
- unpadded decimal for indexes `100..127`.

Canonical extension artifact filenames are:

```text
qr_document-<index>-<doc_id>.pdf
recovery_document-<index>-<doc_id>.pdf
recovery_kit-<index>-<doc_id>.pdf
recovery_kit_index-<index>-<doc_id>.pdf
```

`<index>` is the canonical directory index and `<doc_id>` is the lowercase 16-hex document ID.
`qr_document`, `recovery_document`, and `recovery_kit` are required. `recovery_kit_index` is
permitted only when the selected render style requires it.

Their roles are distinct:

- `qr_document-*` is the machine-readable MAIN and AUTH carrier;
- `recovery_document-*` is the manual fallback MAIN and AUTH carrier;
- `recovery_kit-*` is the required chain-bound browser recovery tool described in Section 7; and
- `recovery_kit_index-*` is an optional navigation/index sheet required only by a render style.

Neither recovery-kit role is a MAIN or AUTH carrier, and `recovery_kit_index-*` is informational;
its presence does not add recovery payload redundancy.

There is no separate canonical extension AUTH artifact or filename. AUTH transport reuses the
machine-readable `qr_document-*` carrier set beside the corresponding MAIN frames; the
`recovery_document-*` fallback sections represent the expected MAIN and AUTH frames together.

Canonical extension shard filenames are:

```text
shard-<index>-<doc_id>-<share_index>-of-<share_count>.pdf
signing-key-shard-<index>-<doc_id>-<share_index>-of-<share_count>.pdf
```

`share_index` and `share_count` are unpadded positive decimal integers satisfying
`1 <= share_index <= share_count <= 255`.

When a shard role is present, it MUST form one complete set with a single `share_count` and indexes
`1..share_count`. Passphrase and signing-key shards are independent roles. Validation MUST load each
shard PDF, recover exactly one `KEY_DOCUMENT` frame, and verify its signed payload against:

- the filename index and count;
- the extension ciphertext `doc_id` and `doc_hash`;
- the artifact key type;
- `root_sign_pub` from Section 7.2 of the core format specification;
- every other member of the same shard set.

The canonical filename grammar is an export-layout contract. Content import MAY accept arbitrary
user-supplied filenames when their contents provide complete authenticated carriers.

## 5) Carrier Roles and Fallback Audits

In a canonical extension directory, `qr_document-*` is the only payload-bearing machine-readable
MAIN role. `recovery_document-*` is a human-readable fallback for manual transcription when QR input
is unavailable or damaged.

Manual fallback text MAY be accepted through an explicit text-input surface. Implementations MUST
NOT extract fallback text from a PDF or image and treat it as an authoritative content-import or
chain-replay carrier.

Before promotion, publication MUST validate every payload-bearing machine-readable carrier. Initial
publication and later append validation MUST also exact-validate the extractable text layer of every
required fallback-bearing PDF:

- the root `recovery_document.pdf` against its expected MAIN and AUTH frames;
- every canonical root shard PDF against its expected `KEY_DOCUMENT` frame;
- every extension `recovery_document-*` against its expected MAIN and AUTH frames;
- every canonical extension shard PDF against its expected `KEY_DOCUMENT` frame.

Exact validation MUST identify the designated canonical sections, decode them in document order
under the core fallback rules, and require a one-to-one byte match with the expected ordered frames
and roles. It MUST fail when the PDF or text layer is unusable or a required section is missing,
malformed, extra, reordered, or mismatched.

This audit binds the extractable fallback encoding to the authenticated carrier identity. It does
not prove physical visibility, legibility, or the presence of every carrier ever produced. It is not
a signed publication manifest.

### 5.1) Canonical Fallback Section Grammar

This subsection defines logical text sections, not typography or page geometry. A canonical PDF
encoder MUST expose an extractable text layer that has a unique, order-preserving mapping to this
grammar. PDF extraction may split or merge visual lines, but if a validator cannot recover one
unambiguous logical stream, validation MUST fail.

For title recognition, define `normalize_title(line)` as follows:

1. require every code point in `line` to be ASCII;
2. map ASCII `A` through `Z` to `a` through `z`;
3. collapse each run of ASCII whitespace to one U+0020 space; and
4. remove leading and trailing U+0020, `=`, `-`, and `:` characters.

The canonical emitted recovery-section titles are `Auth Frame` and `Main Frame`. A validator MAY
recognize decoration and case variants only through `normalize_title`; their normalized values MUST
be `auth frame` and `main frame`. One title group is one or more consecutive extracted lines with
the same normalized title. Multiple lines in one group tolerate duplicate text extraction; a later
second group with the same title is a duplicate section and MUST be rejected.

A root or extension recovery document MUST map to exactly this ordered grammar:

```text
Auth Frame
<fallback text for exactly one AUTH frame>
Main Frame
<fallback text for exactly one MAIN frame with INDEX = 0 and TOTAL = 1>
```

The AUTH payload region begins after the `Auth Frame` title group and ends before the `Main Frame`
title group. The MAIN payload region begins after the `Main Frame` title group. Within either
region, numbered fallback payload lines are selected in logical document order and decoded under
Section 11 of the core format specification. Page headers, footers, and continuation layout are not
payload. A region MUST yield exactly one canonical frame and MUST NOT contain another designated
fallback payload before the next section or end of document.

A canonical shard PDF has one logical fallback section containing exactly one `KEY_DOCUMENT`
frame. Its canonical designated heading is `Manual Transcription`, `Scan In Offline Kit`, or
`Shard Payload`. Repetition of the same heading MAY identify page continuation of that one section;
it MUST NOT introduce a second frame. The canonical filename establishes whether the expected frame
is a passphrase or signing-key shard, and exact validation applies the role checks in Sections 3 and
4 of this profile.

## 6) Extension Shard Custody Policies

Every extension publication MUST use exactly one passphrase-shard policy:

- **self-contained:** publish one complete extension-specific passphrase shard set;
- **reuse-root:** publish no extension-specific passphrase shards and identify the validated root
  shard threshold and share count in the recovery guidance.

A requested extension passphrase shard count of zero is valid only with `reuse-root`. It MUST NOT
select plaintext passphrase storage or cause a plaintext passphrase to be embedded in a recovery
document.

Signing-key recovery sheets are redundant custody copies of signing authority. They MUST NOT be
presented as a second append approval, second factor, or dual-control requirement.

The passphrase-shard policy is a publication-time custody rule, not an authenticated extension
envelope field. It does not change wire identity and cannot be inferred from absent carriers. A
validator observing a complete extension-specific shard set MAY classify the publication as
self-contained. In its absence, a validator MUST NOT claim that `reuse-root` was the original
policy, or distinguish intentional reuse from lost self-contained shards, solely from the remaining
artifacts. Root-shard recovery may still be attempted when the supplied authenticated material
supports it.

## 7) Recovery-Kit Metadata

Every canonical extension publication MUST include a replacement chain-bound `recovery_kit-*` PDF.
The embedded browser payload MUST assign a JSON object to
`globalThis.__ETHERNITY_KIT_METADATA__`. Metadata version 1 uses lowercase field names and JSON
types exactly as shown:

```json
{
  "capability": "ethernity-chain-bound-recovery",
  "version": 1,
  "root_document_hash": "<64 lowercase hex characters>",
  "root_signing_public_key_fingerprint": "<64 lowercase hex characters>",
  "expected_latest_head_hash": "<64 lowercase hex characters>",
  "supported_extension_envelope_versions": [2],
  "supported_extension_schema_versions": [1]
}
```

JSON member order and insignificant whitespace are not semantic.

Field derivation is:

- `root_document_hash`: BLAKE2b-256 of the root ciphertext, encoded as lowercase hex;
- `root_signing_public_key_fingerprint`: SHA-256 of the raw 32-byte Ed25519 root signing public key,
  encoded as lowercase hex;
- `expected_latest_head_hash`: BLAKE2b-256 of the newly published extension ciphertext, encoded as
  lowercase hex.

A chain-bound kit MUST reject recovery unless:

- the supplied root ciphertext hash equals `root_document_hash`;
- the authenticated root signing public key fingerprint equals
  `root_signing_public_key_fingerprint`;
- the latest authenticated supplied extension head equals `expected_latest_head_hash`;
- the kit lists support for extension envelope version 2 and header schema version 1.

The metadata is a pinned expectation carried by the recovery kit, not a field signed into the
extension chain. The kit therefore remains a security-sensitive carrier and MUST be protected with
the same care as the other expected-state records.

An unanchored generic browser tool MUST use:

```json
{
  "capability": "ethernity-unanchored-rescue",
  "version": 1,
  "supported_extension_envelope_versions": [2],
  "supported_extension_schema_versions": [1]
}
```

It MUST be labeled **unanchored rescue kit** and MUST NOT claim to authenticate the globally latest
backup state or an expected extension head.

## 8) Journaled Atomic Publication

Extension publication MUST use the journaled transaction primitive defined here. It MUST:

1. render all required files into one unpublished sibling staging directory;
2. validate the rendered carriers and record their names, sizes, and cryptographic hashes as the
   staging snapshot;
3. acquire a kernel-owned exclusive advisory lock on the persistent regular file `.chain.lock`;
4. while holding that lock, revalidate the authenticated root and complete current chain head, the
   staged snapshot, transaction coordinates, and absence of the final destination;
5. while still holding the lock, write and `fsync` `.transaction.json`, flush and `fsync` every
   staged regular file, then flush the staging directory where the platform exposes directory
   flushing;
6. rename the complete staging directory to its final name as one publication unit;
7. flush the destination parent where the platform exposes directory flushing; and
8. release the advisory lock only after publication is complete.

The transaction journal MUST NOT become visible before the publisher owns `.chain.lock`. This
ensures repair cannot treat an active, pre-publication staging directory as abandoned work.

The advisory lock file MUST NOT be removed after use. Lock ownership belongs to the open kernel file
handle and is released automatically when the process exits. Implementations MUST NOT use the
existence of `.chain.lock`, or a directory created at that path, as the lock state.

Transaction metadata version 1 is a strict JSON object containing:

- `version` set to `1`;
- a unique `transaction_uuid`;
- the authenticated `root_hash`;
- the `expected_parent_hash`, or `null` for a new root publication;
- the `new_index` and `new_hash`; and
- `artifact_snapshot`, excluding `.transaction.json` itself.

The transaction record MAY remain in the promoted directory. It is publication metadata, not a
carrier and not part of canonical filename inventory validation.

Directory metadata flushing is not a portable filesystem operation. Implementations MUST require
regular-file flushing on every platform and MUST flush staging and destination directories where
the platform exposes that operation. A platform without directory flushing MUST still use a
same-filesystem atomic rename, the persistent advisory lock, authenticated head revalidation, and
the transaction journal. Lack of directory flushing MUST NOT disable extension publication, but the
implementation MUST NOT claim that this has the same power-loss metadata guarantee as a successful
directory flush.

Ordinary backup, mint, and restore output are outside this journaled extension publication
guarantee. This profile defines no stronger flushing guarantee for those operations.

A failed validation MUST leave no canonical published extension directory. Staging workspaces MUST
remain outside content import and published-head selection. On restart, a repair operation MUST
authenticate the published chain, transaction coordinates, staged carrier contents, and recorded
snapshot before removing a duplicate committed staging directory. Transaction metadata version 1
does not authenticate the original optional-carrier publication policy, so an implementation MUST
NOT resume an interrupted rename by inferring that policy from mutable staged inventory. A future
transaction version MAY support resume only by authenticating that publication policy. A repair MAY
instead move the entire authenticated, snapshot-matching unpublished transaction to a journaled
quarantine outside the canonical extension namespace, preserving its contents while releasing that
namespace for a fresh Add Files operation. Implementations MUST NOT instruct operators to delete
hidden publication state manually. This repair requirement applies to canonical backup
transactions; interrupted dedicated loose output follows the whole-root abandonment rule in
Section 2.

## 9) Selected Recovery

Browser recovery MUST NOT silently select `latest`. Before recovery begins, the browser MUST always
display the expected-head field and require exactly one explicit freshness basis:

- the `expected_latest_head_hash` embedded in a separately stored chain-bound kit;
- a manually entered expected head `doc_hash`; or
- an explicit acknowledgement reading **Recover latest among supplied pages; freshness unknown**.

The acknowledgement permits replay through the latest supplied validated extension only. It MUST
NOT be represented as proof that no later extension exists. Default recovery MUST fail when no
freshness basis is present or when the selected expected head cannot be reconstructed,
authenticated, and replayed.

Recovery MAY select an earlier target by authenticated extension index or `doc_hash`. Index `0`
means root-only recovery. A recursive canonical-export scan selecting an earlier target MAY ignore
carrier contents after that index while still enforcing the selected-prefix layout rules.

Root-only recovery from a chain-bound extension-aware kit MUST fail unless
`expected_latest_head_hash` equals `root_document_hash`.

A separately stored chain-bound kit is the external trust anchor for root identity, root signing
authority, and expected head. Recovery status MUST distinguish:

- **Internally consistent**: signatures agree with keys carried by the supplied set; and
- **Matched trusted kit**: root identity, signing authority, and expected head match the separately
  stored chain-bound kit.

Without that external anchor, an implementation MUST NOT display **authenticated backup identity**.

`latest` always means latest among the carriers supplied to the operation. This profile defines no
online registry or global head lookup.

## 10) Replacement Shard Minting

Before minting shard documents for an imported extension head, an implementation MUST authenticate
the complete ancestry and replay the selected root-plus-extension chain. It MUST NOT use an
unreconstructed, unauthenticated, or unreplayable head's `doc_id`, `doc_hash`, or AUTH as a shard
binding target.

## 11) Compaction

Compaction MUST:

- reconstruct the latest supplied validated logical state;
- write that state as a fresh standalone envelope v1 backup in a separate output directory;
- preserve the exact chain passphrase and the root sealed/unsealed state;
- preserve the root signing seed exactly when the root is unsealed;
- omit signing-key shard documents when the root is sealed;
- leave every source carrier unchanged.

When authenticated root passphrase shards unlock the source, the compacted checkpoint MUST emit a
fresh passphrase shard set with the same threshold and share count. Filename prefixes, unsigned
metadata, and self-authority shard metadata MUST NOT select the inherited shard policy.

Compaction does not rotate or revoke credentials and does not create a new signing authority. The
checkpoint remains inside the source chain's security boundary. Credential rotation, removal, true
rename, or compromise recovery requires a new backup and retirement of the superseded carriers.

Checkpoint output MUST be written to a sibling staging directory, flush every staged regular file,
and be promoted by same-filesystem atomic rename. Directory metadata MUST be flushed where the
platform exposes that operation. When compacting a canonical backup, the implementation MUST hold
the source `extensions/.chain.lock` from authenticated-head revalidation through checkpoint
promotion. A checkpoint is a new standalone backup and does not use the extension transaction
journal; interrupted checkpoint output can be recreated without changing the source chain.
