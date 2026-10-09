# Design decisions

This page explains the reasons behind Ethernity's format and recovery behavior. The
[format specification](format.md) and [update and recovery rules](extension_publication_rules.md)
define the requirements. [Advanced operations](advanced_operations.md) gives command examples;
[Security](../SECURITY.md) describes protections and limits.

## Why split the passphrase

Ethernity encrypts the files with age and can split the passphrase with Shamir secret sharing.
This lets several people or locations hold recovery sheets without any one sheet being enough to
unlock the backup. Splitting a small secret also keeps each sheet small, regardless of the file
contents. The same sharing scheme can protect a signing seed.

Fewer than the required number of shares reveal nothing about the shared secret. Share indexes
are not secret. With a threshold of one, each sheet can recover the secret by itself; storing
sibling sheets apart does not change that. Distribute sheets separately among the people or
locations responsible for them.

Encryption protects the file contents. Checksums and hashes detect corruption. Ed25519 signatures
check backup authentication records and recovery sheets against a signing key. These checks have
different jobs; a set of matching signatures alone does not establish that the key is one you trust.

### Sealed and unsealed backups

An unsealed backup stores its signing seed inside the encrypted manifest. Someone who unlocks the
backup can recover that seed and create signed replacement sheets or updates. Separate signing-key
sheets provide another way to recover the same key.

A sealed backup omits the seed and has no signing-key recovery sheets. Unlocking it therefore does
not recover the key needed to regenerate its signed sheets. Only unsealed originals can be
updated. Changing sealed state requires a new backup document with a different ciphertext hash
and document ID.

The people holding passphrase sheets can decrypt once they have enough sheets. A separate group
holding signing-key sheets can sign authentication records or recovery sheets for a document hash
without decrypting its contents. That second group is not an extra approver for Add Files: anyone
who can unlock an unsealed original already has access to its signing seed.

### Why sheet sets have an identifier

Two independently generated sets of recovery sheets can have the same backup hash, signing key,
threshold, and sheet count. Those fields do not make the shares interchangeable. With Shamir
sharing, any exact-threshold subset defines a polynomial, so the share calculations alone cannot
reliably detect a mixture of sets.

Shard payload v2 adds a signed `set_id`. Readers can reject mixed sets before trying to recover the
secret or create replacement sheets. Released shard v1 remains readable, but lacks this check.
Do not mix sheets across sets even when their other labels match. See the
[v1.1 compatibility entry](format_history.md#v110-2026-03-29).

## Why there are two update modes

Cumulative updates are the default because restoring a version needs only the original backup and
that update. If update 1 adds recovery codes and update 2 changes a password file, update 2 includes
both changes relative to the original. Keep update 1 only if you want to restore its earlier version.

Incremental updates can print less by referring to data in earlier updates. The cost is that every
update through the selected version must survive. Losing update 1 prevents restoring update 2,
even if most files changed again.

| Mode | Can reuse chunks from | Recovery needs |
| --- | --- | --- |
| Cumulative | The original backup and within the current update | Original plus selected update |
| Incremental | The original and earlier updates, and within the current update | Original plus all updates through the selected version |

Both modes use the same encryption, validation, and FastCDC content-defined chunking. Chunking
splits file data into pieces whose boundaries depend on their contents, allowing updates to reuse
unchanged pieces. Cumulative updates repeat still-needed data introduced after the original;
incremental updates can reference it in earlier documents.

The first update fixes the mode and chunk sizes. Local settings cannot change an existing series.
The defaults are a 4 KiB minimum, 16 KiB target, and 64 KiB maximum. Rebuild or a new backup lets a
new series choose different settings. Keeping one mode and one set of sizes per series avoids
having to interpret changes to the dependency rules halfway through recovery.

Incremental writers do not need every historical chunk's bytes in memory. They can keep the current
file set's chunks and earlier chunk identifiers. If a file changes from A to B and then back to A,
the new input supplies A's bytes and hash; the update can reference the old chunk again.

Add Files changes only selected paths. Omitting a file leaves it in the backup, and selecting a
new name does not remove the old name. A file named `a` also cannot coexist with a file named
`a/b`. Deletion, true rename, or removal of such a conflict requires a new backup.

## Why updates must fit Rebuild

Rebuild lets someone replace an update history with a standalone backup. Each new update therefore
checks that the resulting files still fit that format. Add Files and Rebuild share the same
preparation, including automatic compression, file metadata, encryption overhead, and standalone
limits. The 1 MiB ceiling applies to encrypted output, so compressible raw input can be larger.
The check reserves space for the widest supported creation timestamp so a later date does not
break the size guarantee.

An older update history may still restore within the recovery limits even when its combined files
are too large for Rebuild. Recovery remains available. Replacing large files with smaller ones
can bring the file set within the limit again; see [Advanced operations](advanced_operations.md).

### Why Rebuild creates new sheets

Rebuild creates new ciphertext with a new identity. Recovery sheets are bound to a document hash,
so the rebuilt backup needs fresh sheets even when its passphrase stays the same.

| Source | Passphrase after Rebuild | Signing key after Rebuild |
| --- | --- | --- |
| Unsealed | Preserved | Preserved from the encrypted manifest |
| Sealed | Preserved | Newly generated because the manifest has no signing seed |

Rebuild preserves the sealed state. Its new AUTH record identifies the resulting signing key.
It does not take separate signing-key recovery inputs for a sealed source. Rebuild does not revoke
old passphrases or signing keys; changing credentials after compromise requires a new backup.

Replacement sheets for an existing update series are bound to its original backup. They can
unlock any intact version of that series, even if a later update is lost. A complete new set has a
new signed set identifier; compatible replacements keep an existing set bound to the original.
Earlier sets bound to a particular update still need that update. A complete replacement set is
needed to gain coverage of the original alone.

Add Files delegates optional sheet creation to Replace Recovery Docs after the update is saved.
The sheets go outside the update folder so later scans do not accidentally collect older sets.
An error while making sheets does not undo the update. Neither replacement nor Rebuild revokes
previous sheets when the credentials they recover remain unchanged.

## How documents identify a version

A document's contents establish its identity. Filenames, folder order, and scan dates do not.
The same backup can arrive as a PDF, scanned pages, saved QR data, or explicitly supplied fallback
text. This lets people reorganize stored copies without changing what they can recover. Add Files
can use these inputs directly and writes to a separate destination.

Signatures, hashes, and encrypted headers connect an update to its original backup. Cumulative
updates point to the original; incremental updates also depend on earlier updates. Neither model
can prove that no later update exists elsewhere. Cumulative recovery also cannot establish the
history of earlier updates it did not receive.

For example, an original backup and cumulative update 2 can restore version 2. They cannot tell
you whether update 3 is in another drawer. Two people can also make different updates from the
same version. Either branch may validate alone; supplying conflicting branches is ambiguous and
recovery rejects it.

A trusted full fingerprint recorded separately can identify the version you expect. A fingerprint
found beside an untrusted backup is not automatically an independent reference. After full
verification, a trusted update hash establishes the selected update, original backup, and signing
key. A trusted unsealed standalone hash also establishes its seed-derived key. A sealed backup
contains no seed, so checking its AUTH key needs a separately trusted signing-key fingerprint.

The [version-check rules](extension_publication_rules.md#restore-and-version-checks) define which
operations require an expected version or explicit acknowledgement that a newer copy might exist.
Desktop Restore can recover supplied documents without that acknowledgement and reports the
limited scope of its result. The browser recovery kit is reusable across backups; it has no
built-in trusted backup identity. Document IDs can link pages from one backup together, so they
do not provide anonymity.

## Why there are QR codes and printed text

Both carry the same encrypted data and authentication records. QR codes support scanning; text
provides a way to transcribe the data if scanning fails. Newly generated output is checked to make
sure its QR data and designated text sections agree. Imported data only needs a complete valid
representation, so recovery does not require both original PDFs.

Extracting matching text from a PDF cannot prove the print is visible or legible. It also cannot
prove that every recovery sheet was published. Released document v1 has no inventory that could
show an entirely missing sheet role. Output checks and input checks therefore have different jobs;
the [document validation rules](extension_publication_rules.md#check-the-generated-documents)
keep those requirements separate.

The format supports raw QR bytes and unpadded Base64 text. Byte-oriented scanners can try raw
frames first and fall back to Base64. Text payload input requires Base64. The original document
and manifest do not carry a QR codec flag. The
[transport rules](format.md#10-qr-payload-transport) define these two supported encodings.

## Why recovery has limits

A small compressed file, PDF, or encryption header can ask a reader to do far more work than its
size suggests. Limits cover encrypted and decompressed bytes, document and file counts, QR data,
and processing time. Recovery rejects excessive input rather than parsing only part of it.
QR density limits also reduce the risk of printing codes that cannot be scanned.

The [format limits](format.md#17-resource-limits) and
[update limits](format.md#194-extension-chain-rules) define the byte and count bounds.
Decompression checks the expected uncompressed size before starting and stops if output exceeds
it. Text parsing also caps source bytes, line count, and normalized z-base-32 characters.

### Encryption work

An age scrypt header records the work factor used for its passphrase. Desktop and browser readers
check that public header before starting decryption. One stanza with factor `log_n` costs
`2^log_n` work units, charged to a shared budget for the operation.

| Reader | Maximum `log_n` | Maximum total work per operation |
| --- | --- | --- |
| Desktop | 21 | `8 * 2^21` |
| Browser | 20 | `8 * 2^20` |

These are recovery safety limits, not changes to the released v1 grammar. Supported factors are
handled automatically; excessive work is rejected without an override. Decryption runs in
workers that can be terminated on cancellation or timeout. Desktop workers also enforce CPU and
memory limits. Work must not continue in the application process after a worker is stopped.

### PDFs and images

The desktop reader validates input files and symlinks before parsing. Each PDF or image is parsed
and QR-decoded in a fresh process. Limits cover memory, CPU, elapsed time, PDF pages, embedded
images, pixels, decoded payloads, and data returned by the worker. The whole scan also has file,
payload, and elapsed-time limits.

Only bounded QR payload bytes return to the application; parser objects and image buffers stay
in the worker. Timeout, resource exhaustion, parser failure, cancellation, or source replacement
terminates the process. Platforms that cannot enforce or observe the required limits refuse the
operation instead of parsing inside the application process.

## Why output is staged

Add Files and Rebuild write to a private sibling directory, validate the output, flush its files,
and rename the complete directory into place. An interrupted operation leaves an unpublished
staging directory that recovery ignores. The source documents remain unchanged.

Directory flushing is not available everywhere. POSIX publishers flush the parent directory with
`fsync`; Windows uses the strongest portable guarantee when Python cannot open the directory for
flushing. Neither operation locks the source backup. A lock on one folder could not prevent someone
updating a separate offline copy. The
[publication rules](extension_publication_rules.md#publish-output-and-handle-interruptions) specify
validation, destination checks, and cleanup after an interruption.

## How older backups stay recoverable

Document v2 uses one format version for standalone backups and updates. A separate kind field
selects the body layout. In standalone manifests, the signing seed determines sealed state, and file
sizes determine decompressed payload length. Storing those values again would add checks without
adding information. Both standalone versions still record whether file bytes are raw or gzip
compressed, and both verify decompressed length and file hashes.

Released document v1 is decoded with its original required fields and checks before being converted
to the shared recovery model. Its stored manifest version, sealed flag, and gzip length remain
validated. Keeping this decoder preserves old backups without duplicating the recovery engine or
requiring an old-format writer. Older readers may still reject a newly written format.

Update headers use the same outer document version with the update kind. They authenticate paths,
chunk references, original and parent hashes, chunk sizes, and mode. Standalone source labels remain
because the distinction between an input file and folder affects export behavior. See
[compatibility history](format_history.md) for reader and writer changes by release.

## Reader details that affect recovery

### Passphrase spacing

Ethernity generates 24-word BIP-39 passphrases by default. That length is a creation default, not a
format requirement. Recovery tries the supplied passphrase exactly before trying normalized
single-space text, and only normalizes a checksum-valid BIP-39 phrase. A custom string with an
invalid BIP-39 checksum keeps its exact spacing.

This is a valid 12-word example, not a secret to use for a backup:

```text
abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about
```

Producers likewise normalize whitespace only for checksum-valid BIP-39 phrases. See the
[passphrase rules](format.md#14-passphrase-representation) for the format requirements.

### Text input detection

Automatic detection checks for fallback section markers first: `MAIN FRAME`, `AUTH FRAME`,
`SHARD FRAME`, or `KEY FRAME`. Without markers, it tries QR payload frames on every nonempty line,
then z-base-32 fallback lines. If neither interpretation succeeds for the whole input, it rejects
the input as invalid or ambiguous. Mixing payload and fallback lines in one block is unsupported.

### Paths and encoding

Unicode NFC makes equivalent path spellings compare consistently across systems. For example,
`caf` followed by U+00E9 and `cafe` followed by U+0301 display the same name. NFC does not resolve
case differences on case-insensitive filesystems; avoid pairs such as `Secrets.txt` and
`secrets.txt` for cross-platform recovery. Released v1 also rejects drive-letter-prefixed paths
such as `C:notes.txt`. See [path normalization](format.md#16-path-normalization).

Binary headers use unsigned varints. Integers inside CBOR maps use CBOR encoding. Ethernity retains
length-first deterministic map ordering for compatibility with released backups. AUTH and shard
signatures cover the exact field maps defined in the format specification, excluding the signature
and unknown fields. The [CBOR rules](format.md#22-common-deterministic-cbor-rules) specify the encoding.
Use compliant age and Shamir implementations rather than replacing their algorithms. The Python
implementation uses `pyrage` and `Crypto.Protocol.SecretSharing.Shamir`; an alternative must match
the specified [encryption](format.md#13-encryption) and [sharing](format.md#15-shamir-secret-sharing)
rules.
