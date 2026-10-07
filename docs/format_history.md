# Format compatibility

New Ethernity versions must continue to recover backups produced by released versions. Older
readers and recovery kits may reject newer formats. The released v1.0 and v1.1 golden fixtures
remain unchanged and must continue to recover.

Product versions and document versions are separate. For example, Ethernity v1.2 writes standalone
document v3 and update document v2. This table describes format support; resource limits and
validation still apply to every input.

| Ethernity release | Writes new standalone backups | Reads standalone backups | Reads recovery-sheet payloads | Reads updates |
| --- | --- | --- | --- | --- |
| v1.0.0 and v1.0.1 | Document v1 | Document v1 | Shard v1 | No |
| v1.1.0 | Document v1 | Document v1 | Shard v1 and v2 | No |
| v1.2.0, unreleased | Document v3 | Document v1 and v3 | Shard v1 and v2 | Document v2 |

Use a v1.2 reader or recovery kit for document v3 backups and updates. A v1.0 reader cannot use the
v2 recovery sheets introduced in v1.1, even though the standalone backup format stayed at v1.

The [format specification](format.md) defines encoded data and decoder requirements. The
[update and recovery rules](extension_publication_rules.md) define required operations and output.
[Contributing](../CONTRIBUTING.md#update-the-documentation) explains how to maintain this history.

## v1.2.0, unreleased

### Standalone document v3

New backups and Rebuild output use document v3. It removes the manifest's inner `version`, derives
sealed state from `seed`, and derives decompressed size from file sizes. The encryption,
authentication, payload codecs, and recovery model remain shared with document v1.

Readers still accept released document v1 with its original required-field checks. v1.0 and v1.1
readers and kits reject document v3. Browser recovery of new backups requires a v1.2 kit.

### Updates

This release introduces update document v2. An update can extend an original standalone document
v1 or v3. Earlier readers cannot recover updates.

Updates add or replace files using authenticated hashes, signatures, and content-defined chunks.
The header records cumulative or incremental mode. Cumulative is the default and needs the original
plus the selected update. Incremental mode needs every update through the selected version. Mode
and chunk sizes stay fixed within a series. Both modes share codecs and validation; cumulative
parent hashes refer to the original.

The [update rules](extension_publication_rules.md) also define document-based input selection,
two required output PDFs, passphrase reuse, replacement sheets, reusable kits, and staged writes
that leave sources unchanged. Input identity and ordering come from authenticated contents, so
PDFs, scans, and explicit fallback text can supply the same backup. FastCDC algorithm 1 has bounded
parameters and shared conformance vectors for Python and browser readers.

Each new update must leave files that fit Rebuild's standalone format. Older oversized file sets
remain recoverable within the existing recovery limits. Replacement sheets bind to the original
backup so an intact earlier version remains usable if a later update is lost. Creation and Rebuild
validate the backup and enough sheets from each generated set to recover its secret.

Rebuild keeps the passphrase and sealed state. It keeps the signing key for unsealed sources;
sealed sources receive a new key because their manifests contain no signing seed.

### Reader checks

These changes clarify or tighten validation without changing the released v1 grammar:

- Shamir shares keep their existing GF(2^128) big-endian representation and direct index mapping.
- Fallback decoding removes one dotted rendered line label deterministically.
- Identical AUTH copies are accepted; conflicting AUTH payloads are rejected.
- Raw payload lengths must match exactly, and the existing POSIX path restrictions apply.
- A file set containing both `a` and `a/b`, or another file/ancestor conflict, is rejected before
  export. Older readers could accept such a set and fail while writing it. Encoders do not emit it.
- Original AUTH, embedded or recovered signing seeds, recovery sheets, and update AUTH must identify
  the same public key. This documents the check already enforced by authenticated recovery.

Readers reject signing-key substitution, conflicting authentication records, extra payload bytes,
and incompatible paths. Recovery reports separately whether supplied documents are internally
consistent or match an independently trusted full fingerprint. A sealed original needs a trusted
signing-key fingerprint as well to verify its AUTH key. The
[version-check rules](extension_publication_rules.md#restore-and-version-checks) specify which
operations require an expected version or acknowledgement that a newer copy may exist elsewhere.

PDF/image parsing and age decryption run in disposable workers with resource limits. Scrypt work
factors are checked before decryption, with per-stanza and total-work limits. Supported factors
need no special recovery mode; excessive work is rejected without an override. The
[current recovery limits](format_rationale.md#why-recovery-has-limits) describe desktop and browser
behavior. The frozen v1.2 update fixtures exercise both Python and browser recovery.

### Printed recovery kit

New kit PDFs use two startup codes to create an offline assembly page, followed by numbered
alphanumeric data fragments. The page accepts scans in any order and checks their completeness
and checksums. Base44 packs 15 bytes into 22 characters; the print-set identifier includes the
encoding and fragment size. Roadroller packing reduces the printed application size. These changes
do not alter backup, update, or recovery-sheet formats. Existing printed kits still reconstruct
through their own embedded loaders and do not need reprinting.

## v1.1.0, 2026-03-29

New recovery sheets use shard payload v2, adding a signed 16-byte `set_id`. It lets readers reject
sheets from different sets before recovering a secret or creating replacements, even when the
input contains exactly the required number of sheets.

Readers still accept shard payload v1. Those older sets lack an identifier and cannot reliably
detect an exact-threshold mixture of sets. Readers that only support shard v1 reject new shard v2
sheets. The standalone backup format remains document v1.

## v1.0.0, 2026-03-04

The initial public format established standalone document v1, manifest v1, frame v1, AUTH payload
v1, and shard payload v1. It defined QR transport, fallback text, age encryption, BIP-39
passphrases, and Shamir recovery. Later compatibility changes are measured against this release.
The v1.0.1 packaging update did not change these formats.
