# Ethernity format rationale and recovery guidance

This non-normative page explains design choices and gives storage and recovery guidance. The
[core format specification](format.md) defines serialized data. The
[v1.2 extension publication rules](extension_publication_rules.md) define extension documents and
operations.

## Sealed and unsealed backups

Sealing controls whether the signing seed is recoverable from the encrypted manifest.

Choose based on how the signing seed should be recovered:

- Choose an unsealed backup to recover the signing seed from its encrypted manifest and regenerate
  signed recovery sheets after decryption.
- Choose a sealed backup when the signing seed should not be recoverable from the backup.
  Ethernity leaves it out of the encrypted manifest and does not create signing-key recovery sheets
  for sealed backups. Decryption cannot regenerate their signed recovery sheets.

Changing between sealed and unsealed requires a new backup document, which produces different
ciphertext and therefore different `doc_hash` / `doc_id`.

## What each protection provides

Ethernity recovery combines:

- Encryption (age) for confidentiality and integrity of the backup document.
- Signatures (Ed25519) to authenticate AUTH and shard payloads.
- `doc_hash`/`doc_id` to bind frames and signatures to a specific ciphertext identity.
- Optional Shamir secret sharing to divide passphrases and signing seeds among custodians.

Common custody arrangements:

1. One custodian holds the passphrase directly and can decrypt.

2. N custodians each hold one passphrase shard; any T of N can reconstruct and decrypt. In a sealed
   backup, they cannot recover the signing seed from the manifest.

3. Group A holds passphrase shards. Group B holds signing-key shards and can create new signed AUTH
   or shard payloads for a `doc_hash` without decrypting it. Group B is not an additional approver
   for Add Files.

Security guidance:

- Use a single decryption failure message for wrong passphrases and corrupted data, so callers
  cannot distinguish the failures to probe encrypted data.
- `doc_id`/`doc_hash` enable correlation across documents; privacy/anonymity is not a goal.

## How recovery identifies the latest update

Extension replay authenticates the chain prefix present in the supplied documents. It checks
that the supplied extensions link back to the selected root backup and are signed by its signing
key. It cannot establish that no later extension was ever created.

Consequences:

- A stale recovery set that contains root plus extensions `1..N` can be indistinguishable from a
  complete chain whose latest head is `N`.
- Missing, corrupt, forked, or unauthenticated supplied extensions still fail closed; the limitation
  is only absence detection for documents that were not supplied.
- The offline browser recovery kit is reusable across backups. After complete authenticated replay,
  an independently trusted full extension-head hash fixes the root identity and signing key through
  the extension's root-hash commitment and the unsealed root's signing seed. A trusted standalone-root
  hash fixes root identity and unsealed signing key, but a sealed root has no embedded seed to verify its
  AUTH signing key against; that requires an independently trusted signing-key fingerprint.
  That fingerprint is not part of content import itself, and a record found beside the backup is not
  independently trusted by default.
- Two publishers can append independently from the same head and create valid forks. Supplying both
  conflicting branches is an ambiguity and fails closed, but either branch can validate in
  isolation.
  `Latest` therefore always means latest among the documents supplied to that operation. Add Files
  and browser recovery require a manually entered expected head or an explicit
  freshness-unknown acknowledgement before using that target. The current release deliberately has
  no global head registry or online coordination requirement.

## Who can add files and when to create a new backup

An appendable root is unsealed. Its encrypted manifest contains the chain signing seed. Anyone who
has the root backup documents and can unlock that manifest can both recover data and sign a valid
extension. Signing-key recovery sheets provide another way to recover the same seed. They do not
add a second factor or an independent approval step.

Rebuilding preserves the passphrase and sealed state. For unsealed sources, it also preserves the
signing seed and key. A sealed manifest has no seed, and Rebuild does not accept separate
signing-key recovery inputs, so a rebuilt sealed backup receives a new signing key. Its
new AUTH identifies that key. Rebuild does not revoke old passphrases or signing keys.
After credential compromise, or when intentional rotation is needed, recover the desired files,
use **Create backup** with new credentials, and retire the old backup documents.

Every newly published update must leave a file set that fits a standalone backup. Add Files encodes
the combined files using the same preparation as Rebuild, including file metadata, automatic
compression, encryption overhead, and all standalone limits. The 1 MiB limit applies to the final
ciphertext, not the raw file bytes. This keeps Rebuild available when history grows inconvenient.
The check leaves room for the widest supported creation timestamp, so rebuilding on another date
cannot push the backup over the size limit.
Recovery still accepts already-created oversized chains within its existing limits. Those files
can be restored even when Rebuild refuses their size; replacements that reduce the state enough
can make such a chain rebuildable again.

Add Files is add-or-replace rather than filesystem synchronization. A matching path is replaced and
an omitted path remains in the current file set. A rename adds the new path without removing the old
one. To remove or truly rename content, recover the desired files, use **Create backup** without the
old path, and retire every paper and digital copy whose historical content must no longer be usable.
The combined state must also form a restorable file tree. Files named `a` and `a/b` cannot coexist;
an update that creates either ancestor conflict is refused. A new backup is needed to make that
change because an extension cannot remove the conflicting path.

Add Files can optionally follow a successful append by invoking Replace Recovery Docs for the new
authenticated head. Add Files does not create the sheets itself. The output stays outside the
extension output package so later update and recovery scans do not absorb old replacement sheets
unintentionally.

Replacement sheets always bind to the original root, even when the operation checks a later
selected head. They unlock any intact prefix with that root, so losing a later update does not
make the new sheets unusable for the surviving older version. Sheets recover credentials; they
do not establish which version is current. A full new set gets a separate signed set identifier;
compatible replacement sheets stay in an existing root-bound set. Earlier head-bound sets need
complete replacement to gain root-only recovery coverage. Old sets remain sensitive because
unchanged credentials do not revoke them.

Rebuild changes ciphertext identity and creates fresh sheets bound to its new root. Publication
checks the new backup and recovery sheets. Users should test restoration before retiring the source
and record the new full fingerprint separately if they use expected-version checks.

## Documents identify the chain

The same authenticated root and extensions can arrive as original PDFs, scanned paper, saved QR
payloads, or explicit fallback text. Add Files uses those documents directly and writes a separate
extension package. It does not need a writable source folder or a preliminary Rebuild.

Generated filenames and folders help people organize their documents. Renaming or moving a document
does not change its identity, ancestry, or eligibility for an update. Authentication derives those
facts from ciphertext, AUTH, and decrypted headers. A source folder also cannot prove that a newer
offline update does not exist, so Add Files requires an expected head or an explicit
freshness-unknown acknowledgement for every source medium.

## Fallback text checks

Machine-readable ciphertext, AUTH frames, and signed shard payloads remain authoritative. The v1.2
publication rules also require exact validation of extractable fallback sections in newly generated
output before publication so fallback bytes match the authenticated ciphertext and shard payloads.
Imported documents do not need a companion fallback PDF; any complete authenticated set of QR
payloads or fallback text can supply their content.

Text extraction cannot establish physical visibility or legibility, and it supplies no signed record
of which recovery sheets were published. In particular, backup document v1 cannot establish that an
entirely absent shard role was ever published. The publication rules define which omissions must fail
validation and which cannot be
detected from the available documents.

## Publication interruption

A private `.staging-*` directory beside the chosen destination is unpublished and ignored by folder
discovery and recovery. There is no journal, repair command, resume path, or quarantine step. After
confirming that no Add Files process is running, a user may remove an abandoned staging directory.
A fresh append uses a new staging directory and publishes from its reviewed authenticated input
snapshot.

Directory durability is not uniformly exposed by every operating system and filesystem. Extension
publication therefore requires flushed regular files, validated output, and a same-filesystem
atomic rename into an absent destination. POSIX publishers also flush the directory with `fsync`.
Windows continues with its strongest portable guarantee when Python cannot open a
directory for flushing. Rebuilding uses the same staged publication steps and creates a separate
standalone backup. Neither operation locks or changes the source documents. Independent publishers
can create valid forks from the same head; a source-folder lock could not prevent that across
offline copies.

## Why shard sets have `set_id`

Shard payload version 2 adds a signed `set_id` to each shard in a shard set.

The identifier prevents accidental mixing of shard sets:

- Distinct shard sets for the same `doc_hash` and signing key can otherwise look mutually valid.
- With plain Shamir shares, any exact-threshold subset defines some polynomial, so mixed sets are
  not reliably detectable from share math alone.
- A signed `set_id` lets decoders reject mixed exact-threshold inputs before reconstruction or
  replacement creation.

When replacing shards:

- When rotating or replacing shards for the same backup, treat `set_id` as the shard-set identity.
- Do not mix recovery sheets across shard sets just because `doc_hash`, threshold, or share
  count match.

A threshold of one means that each shard can reconstruct its secret by itself. Physical
separation from sibling shards does not prevent recovery in this configuration. Treat each
threshold-one passphrase shard as a complete recovery secret and each threshold-one signing-key
shard as a complete signing seed.

## Recovery input detection order

When recovery input mode is auto-detected, readers should apply this strict order:

1. If fallback section markers are present (`MAIN FRAME`, `AUTH FRAME`, `SHARD FRAME`, `KEY FRAME`),
   parse as fallback sections.
2. Otherwise, if all non-empty lines decode as QR payload frames, parse as payload mode.
3. Otherwise, if all non-empty lines are valid z-base-32 fallback lines, parse as fallback mode.
4. Otherwise, fail with an explicit invalid/ambiguous-input error.

Mixing payload and fallback lines in one input block is not supported.

## Why recovery inputs are bounded

Format v1 uses strict fail-closed limits centered on a `1 MiB` ciphertext ceiling.

The limits:

- Keep worst-case memory/CPU bounded for CLI recovery and frame parsing paths.
- Keep fallback-MAIN behavior aligned with single-frame recovery text output.
- Keep limits round and predictable for readers, writers, and tests.

Consequences:

- Oversized documents are rejected instead of partially parsed.
- QR payload limits are conservative to avoid generating unreadable, high-density codes.
- Fallback parsing applies independent caps to source bytes, filtered line count, and normalized
  z-base-32 character count so malformed or adversarial text fails early.
- The size check applies to ciphertext: writers may accept inputs larger than 1 MiB
  when pre-encryption compression allows the final ciphertext to stay within `MAX_CIPHERTEXT_BYTES`.

The extension rules add chain-wide limits because otherwise individually valid documents can
accumulate unbounded recovery work. A chain stops at 128 total documents, 64 MiB aggregate
ciphertext, and 256 MiB cumulative decoded inline chunks. Rebuilding creates a fresh
standalone root when a chain is near any limit. The standalone check during Add Files prevents updates
from growing the current state beyond Rebuild's capacity. Rebuild uses automatic compression even
if the source root used a raw payload; history size does not change the standalone size check.
KDF work limits are recovery safety checks, not a stable-v1 format restriction. Desktop and browser
recovery parse every public scrypt stanza before starting a KDF, enforce both per-stanza and
cumulative work ceilings, and run work within those limits in disposable workers. Normal desktop
recovery accepts through `log_n = 20`; `log_n = 21` requires an explicit retry with higher limits.
The guided app offers that retry only after a normal work-limit failure and displays the estimated
peak scrypt memory. Approval applies only to the failed restore attempt, not subsequent restores.
The scriptable command retains its explicit override flag. Values above `21` and
cumulative work above the compatibility ceiling are always rejected. Browser recovery retains its
more conservative automatic threshold. Cancellation, CPU/memory ceilings, or wall-time expiry
terminate the active worker rather than leaving an in-process KDF running.

FastCDC chunk sizes are advanced tuning values, not format constants. Ethernity defaults to a
16 KiB target, 4 KiB minimum, and 64 KiB maximum. The first extension authenticates those three
sizes, so later appends use them even if local settings change. Different sizes require a new or
rebuilt standalone backup.

Append deduplication does not require retaining every historical decoded chunk. Writers can retain
the current file set's chunk bytes plus the set of all earlier chunk identifiers. If new input
returns to old content (for example A to B to A), its bytes establish the matching identifier and
the new extension references the historical chunk instead of emitting it again.

## Payload compression metadata (manifest v1)

Stable v1 records file-data compression in the manifest without a version bump:

- `payload_codec`: required `"raw"` or `"gzip"`
- `payload_raw_len`: required only when `payload_codec == "gzip"`

Compression behavior:

- Writers that use gzip compress file bytes before encrypting the backup document.
- Recovery reads raw file bytes or decompresses gzip bytes as specified by the manifest, then
  slices individual files and checks their hashes.
- To limit memory use from compressed inputs, readers check the declared uncompressed length
  against `MAX_DECOMPRESSED_PAYLOAD_BYTES` before decompression and stop if decoded bytes exceed
  that length.

Compatibility:

- Stable v1 readers reject manifests without `payload_codec`.
- Readers that do not support `gzip` metadata may fail to recover gzip-coded backup documents.

## QR transport

Version 1 supports two QR transport codecs as defined in the core format specification:

- `raw` frame bytes (preferred for QR scan transport)
- unpadded `base64` text (for text input)

Neither the manifest nor the backup document header identifies the QR payload codec in v1. Recovery
parsers handle this by source type:

- byte-oriented scan sources can decode raw directly and fallback to base64 text decoding
- text sources remain strict unpadded base64 parsing

Readers and writers should not negotiate or introduce additional codecs in v1.

## PDF and image parsing

The CLI treats each PDF or image as hostile input. Input-file validation and symlink checks happen
before parsing. Each valid input file is then parsed and QR-decoded in a fresh spawned
worker with memory, CPU, wall-time, PDF-page, embedded-image, pixel, decoded-payload, and IPC-output
ceilings. The complete scan also has file-count, aggregate payload, and wall-time ceilings.

Workers are disposable: timeout, resource exhaustion, parser failure, user cancellation, or source
replacement terminates the subprocess. Parser objects and decoded image buffers never return to the
main application; only bounded QR payload bytes cross the process boundary. Platforms that cannot
install or observe the required worker limits fail closed instead of silently parsing in-process.

## Passphrases and BIP-39 spacing

Ethernity generates 24-word BIP-39 passphrases by default. This is not a format requirement.

Producers normalize whitespace only when the text is a checksum-valid BIP-39 mnemonic. Recovery
tries the supplied string exactly first, then may retry its distinct normalized single-space BIP-39
form. Word-list-shaped custom strings with an invalid checksum remain exact non-BIP-39 passphrases.

Example (12 words):

```
abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about
```

## Storing Shamir shares

Any Shamir library may be used if it matches the field parameters and encoding rules in the core
format specification.

Python reference library:

- Secret sharing: `pycryptodome` (`Crypto.Protocol.SecretSharing.Shamir`).

Storage guidance:

- Shares are information-theoretically secure: T-1 shares reveal nothing.
- Share indices are not secret.
- Shares should be distributed to independent custodians.
- Never store multiple shares together.

## Why paths use Unicode NFC

Unicode paths can have multiple byte representations that render the same.

Example (visual string: "cafe"):

- NFC (composed): "caf" + U+00E9
- NFD (decomposed): "caf" + U+0065 + U+0301

Different operating systems use different forms (for example, macOS commonly uses NFD). NFC
normalization makes path matching consistent across platforms.

NFC normalization does not solve case-folding differences on case-insensitive filesystems.
Avoid case-only path distinctions (for example, `Secrets.txt` vs `secrets.txt`) when you expect
cross-platform recovery or extraction.

Stable v1 also rejects drive-letter-prefixed paths (for example, `C:notes.txt`) to avoid
ambiguous drive-prefix handling across platforms and extractors.

## Age encryption

Readers and writers should use a compliant age library rather than implement age directly.

Python reference library:

- Encryption/decryption: `pyrage` (age passphrase recipient).

Scrypt parameters (work factor, salt, etc.) are defined by the age scrypt recipient stanza.

## Varint and CBOR integer encoding

The format uses unsigned varints (uvarint) only in the backup document and frame binary headers.

CBOR payloads (manifest, auth, shard) are CBOR maps:

- Integer fields inside these payloads use CBOR integer encoding, not uvarint. Use deterministic
  CBOR where the specification requires it.
- When a signature covers a CBOR payload, sign its deterministic CBOR bytes with the signature field
  omitted. Do not re-encode its integer fields as uvarints.
