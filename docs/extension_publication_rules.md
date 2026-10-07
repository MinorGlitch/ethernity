# Backup updates and recovery

These requirements are normative for Ethernity v1.2.0. They cover Add Files, Restore, replacement
recovery sheets, Rebuild, and the offline browser recovery kit. The
[format specification](format.md) defines encoded bytes, cryptographic bindings, update
relationships, and file reconstruction. See [Advanced operations](advanced_operations.md) for
usage examples.

The words MUST, MUST NOT, REQUIRED, SHOULD, SHOULD NOT, RECOMMENDED, MAY, and OPTIONAL have their
BCP 14 meanings when capitalized.

Here, "original backup" means the root document and "update" means an extension document. Updates
use document format v2. Their authenticated header records the update mode and has no inner
version. The original may use released document v1 or current v3. New standalone backups and
Rebuild output use v3. Product release numbers are not stored in the format.

## Shared input checks

Add Files, Restore, and Rebuild MUST identify a backup and its updates from authenticated document
contents. PDFs, scans, QR payloads, and explicitly supplied fallback text are equivalent sources.
Filenames, folder names, scan times, and directory order MUST NOT determine identity, update
order, parent relationships, or whether a backup can be updated.

Add Files MUST accept complete authenticated documents with the required original signing key,
regardless of their filenames, directory layout, or source medium. It MUST NOT require a prior
Restore or Rebuild. It MUST treat source documents as read-only and write to a separate destination;
source folders need not be writable.

Before assessing an update, Add Files MUST validate:

- the original MAIN ciphertext and its AUTH binding;
- the original signing public key derived from the authenticated manifest;
- every supplied update's AUTH binding and signature against that key;
- update indexes, original and parent hashes, fixed mode and chunk sizes, and the dependencies
  required by that mode;
- file entries, chunk identities and references, and size and count limits;
- reconstruction of one authenticated file set.

The [chain rules](format.md#194-extension-chain-rules) define these checks. Validation and
reconstruction MUST use the same documents, parent relationships, chunk definitions, and limits.
They MUST NOT follow different rules that can disagree. Reconstruction MUST reject conflicting
chunk bytes, mismatched chunk boundaries, missing references, invalid size or hash claims,
exceeded limits, duplicate authenticated indexes, and conflicting update histories. Chunk IDs are
SHA-256 hashes of decoded chunk bytes.

Imported MAIN, AUTH, and recovery sheets used for unlocking MUST be authenticated. Import MUST NOT
require named PDFs or a companion text PDF just because both were generated originally. Manual
fallback text MAY be accepted through explicit text input. Readers MUST NOT use arbitrary text
scraped from a PDF or image as backup or update input.

Input checks, including symlink, size, and file-count checks, MUST NOT require a particular folder
layout. Folder discovery and import MUST ignore private sibling `.staging-*` directories.

## Create an update

Add Files adds new paths and replaces selected existing paths. Omitted paths remain unchanged.
Deleting or truly renaming a path requires a new backup.

### Choose the update mode once

New series MUST default to cumulative updates. Incremental mode MAY be offered as an advanced
choice for the first update.

| Mode | What an update carries | Documents needed to restore that version |
| --- | --- | --- |
| Cumulative | All current changes relative to the original | Original backup and selected update |
| Incremental | Changes that can reuse data from earlier updates | Original backup and every update through the selected version |

Both modes also need the passphrase or enough recovery sheets. Earlier cumulative updates are
needed only to restore their earlier versions.

Later updates MUST retain the authenticated mode. A conflicting requested mode MUST fail before
publication. Changing modes requires Rebuild or a new standalone backup. Recovery MUST detect the
mode from authenticated headers without asking the user to choose it.

Both modes MUST share chunking, encryption, authentication, limits, rendering, and publication
checks. The mode changes which earlier chunks may be reused and which file entries the update
carries.

New v1.2 series MUST use FastCDC algorithm 1 as defined in the
[format specification](format.md#19-extension-chain-format-extension-document). Applications MAY
expose minimum, target, and maximum chunk sizes before the first update. That update authenticates
and fixes the sizes; every later update MUST use them. Local settings changes MUST NOT alter an
existing series. Other sizes require a new or rebuilt standalone backup.

### Unlock and check capacity

Updates use the original backup's passphrase and signing key. Add Files MAY unlock the original
with its passphrase or enough authenticated recovery sheets. It MUST NOT offer a separate update
unlock policy or generate recovery sheets itself.

Every accepted update MUST leave a file set that Rebuild can encode as a valid standalone backup.
Assessment and execution MUST use the shared standalone preparation defined in
[Section 19.4](format.md#194-extension-chain-rules), including automatic compression, file metadata,
encryption overhead, and all standalone limits. The ciphertext ceiling remains 1 MiB.

A failed capacity check MUST block publication and leave the existing backup unchanged. File path
conflicts, such as files named `a` and `a/b`, MUST also block publication. Readers MUST still recover
earlier oversized file sets within the recovery limits. A replacement update MAY reduce such a
file set until it fits.

### Write two update documents

Each published update MUST contain exactly two regular PDF files:

| Recommended filename | Contents |
| --- | --- |
| `qr_document-<index>-<doc_id>.pdf` | MAIN and AUTH as QR payloads |
| `recovery_document-<index>-<doc_id>.pdf` | Exact text fallback for the same MAIN and AUTH |

`<index>` is the authenticated update index, with a leading zero for 1 through 9. `<doc_id>` is the
lowercase 16-hex document ID of the update ciphertext. Users MAY rename, move, copy, or scan the
files. No numbered directory layout is required.

When no output folder is chosen, the app and command runner use
`backup-<original-id>-update-<index>` in the current directory. `<original-id>` is the first 16
hex characters of the authenticated root document hash. The preview MUST show the resolved
destination before publication. Users MAY choose another folder or name. An existing destination
MUST NOT be overwritten or merged with the new update.

Every page of both update documents MUST identify the original backup ID, update number, and
the update's own document ID. These printed labels help organize pages; recovery continues to
verify identity and dependencies from the authenticated contents.

Both documents and the preview MUST state which documents to keep for the selected mode. They
MUST NOT describe earlier cumulative updates as recovery dependencies. Recovery also requires the
sheets or passphrase and the offline kit or another compatible recovery tool.

The output has no separate AUTH file, kit, kit index, passphrase sheet, or signing-key sheet.
Render styles MUST NOT add, remove, rename, or condition these document roles. Style capabilities
may change presentation only. The text recovery document MUST NOT contain a plaintext passphrase
or private signing key.

### Check the generated documents

Before publication, the publisher MUST scan both PDFs. The QR document MUST reconstruct the
expected update ciphertext and required AUTH. The recovery document's QR and designated text
sections MUST contain the same ciphertext and AUTH.

The recovery document has exactly two designated sections, in this order:

```text
Auth Frame
<fallback text for exactly one AUTH frame>
Main Frame
<fallback text for exactly one MAIN frame with INDEX = 0 and TOTAL = 1>
```

Validation MUST reject missing, malformed, extra, reordered, or mismatched sections. Extracted PDF
text proves agreement with the payload bytes; it does not prove that the print is legible or
provide a signed inventory of published sheets.

## Restore and version checks

Restore may select the original backup, an authenticated update index, an authenticated update
`doc_hash`, or the latest valid version among the supplied documents. It uses the dependencies
required by the authenticated mode.

Before Add Files, Rebuild, replacement-sheet creation from imported updates, or latest-version
browser recovery, the user MUST either supply an expected full version hash or explicitly
acknowledge that a newer version may exist elsewhere. These checks govern the operation and do not
add fields to the encoded format. Acknowledgement permits use of the supplied version; it does not
establish that no later offline copy exists.

Desktop Restore MAY recover the latest valid supplied version without an expected hash or a
freshness acknowledgement. It MUST report that the result covers only the supplied documents.
Whenever an expected hash is supplied, it MUST match the recovered version. A requested version
MUST fail if it cannot be authenticated and reconstructed exactly.

Independent updates from the same version can create conflicting branches. Supplying conflicting
branches is ambiguous and fails the input checks; either branch may validate on its own.

Recovery status MUST distinguish documents that are internally consistent from a version verified
against an independently trusted full fingerprint. It MUST report only the guarantees established:

| Trusted reference | What complete authentication and reconstruction establish |
| --- | --- |
| Full update hash | Selected update, original backup identity, and signing public key |
| Full unsealed standalone hash | Original backup identity and its seed-derived signing public key |
| Full sealed standalone hash | Original backup identity; verifying its AUTH signing key also needs an independently trusted signing-key fingerprint |

An update commits to the original hash, and the unsealed original contains the signing seed. A
sealed original has no seed to check against its AUTH key. Without an independently trusted matching
reference, recovery establishes internal consistency only. Even a trusted matching fingerprint
cannot prove that no later version exists.

### Offline browser recovery kit

The kit is reusable across backups and generated independently of them. Its embedded metadata is:

```json
{
  "capability": "ethernity-unanchored-rescue",
  "version": 1,
  "supported_document_versions": [1, 2, 3]
}
```

The same version checks and distinctions above apply to browser recovery.

New printed kits begin with two startup QRs. Concatenating their text in order creates `start.html`:
the first contains the assembly interface and loader, ending with an open hidden textarea; the
second contains Base64-encoded gzip-compressed assembly JavaScript. Whitespace in that Base64 is
ignored. Startup decompression errors MUST stop the page from accepting input.

The remaining QRs contain numbered Base44 fragments and may be entered in any order. Their exact
ASCII layout is `EK1:IIIIIIIIIIII:NNNN:TTTT:LLLL:CCCCCCCC:DATA`. Fields use uppercase hexadecimal:

- `I` is the first 12 hex characters of SHA-256 over the ASCII bytes `base44-15`, followed by
  the compressed kit bytes and the configured chunk size as a four-byte big-endian integer.
  This identifies the software, encoding, and partitioning, not a backup or update chain.
- `N` is the printed QR number, starting at 3. `T` includes the two startup codes.
- `L` is the number of Base44 characters in `DATA`.
- `C` is CRC-32/ISO-HDLC over the ASCII prefix `EK1:I:N:T:L:` followed by `DATA`, excluding
  the checksum field and its following colon. The Python definition is `zlib.crc32`.

The startup configuration fixes the kit identifier, total QR count, concatenated encoded length,
and compression format. After removing scan whitespace, the assembler MUST check every header,
identifier, count, index, length, alphabet character, and checksum before retaining a fragment.
Identical duplicates are ignored; conflicting duplicates are rejected without replacing the accepted
part. An error MUST NOT discard previously accepted parts. These checks detect assembly errors;
they do not authenticate the publisher of the printed software.

Base44 uses the alphabet `0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ$%*+-./:`. Split the compressed
bytes into consecutive 15-byte blocks. Each block is a big-endian integer encoded as exactly 22
base-44 digits, least significant digit first. Zero digits MUST be retained to preserve the block
length. A final block shorter than 15 bytes uses the corresponding digit count below:

| Bytes | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Digits | 2 | 3 | 5 | 6 | 8 | 9 | 11 | 12 | 14 | 15 | 17 | 18 | 20 | 21 | 22 |

Saving requires every data fragment, ordered by index, and the exact encoded length. Concatenate
the fragments before decoding; QR boundaries need not coincide with block boundaries. Decoding
MUST reject a final digit count absent from the table and any block value at least `256**n`, where
`n` is its decoded byte count. Every decoded block MUST retain its full byte count, including
leading zero bytes. The decompressed kit HTML MUST NOT exceed 1,000,000 bytes. Decompression errors
MUST prevent download of a partial kit.

The assembled HTML unpacks the Roadroller-compressed application in a disposable worker. The build
checks that unpacking reproduces the application exactly. The decoder uses a 64 MiB model budget;
the worker is terminated before the recovery interface opens. Both lean and scanner kits retain
the same backup compatibility and use this printed transport. The kit's embedded capability metadata
is part of the application, so it is retained in the downloaded file.

The default data QR contains at most 1839 ASCII characters, including the 41-character header.
At error correction M this fills QR version 29. Custom QR settings can reduce this limit; both
startup codes have independent capacity checks.
This transport is separate from backup frames and recovery sheets. Existing printed kits retain
their own loader and reconstruction rules.

## Replace recovery sheets

Replace Recovery Docs MUST authenticate and reconstruct the selected version and all dependencies
required by its mode before making sheets. Whether the selected version is the original or an
update, every new sheet MUST bind to the original's `doc_hash` and signing public key.

Replacement passphrase sheets MUST unlock the original and any recoverable version based on it.
Losing a later update MUST NOT prevent them from unlocking an intact earlier version. Signing-key
sheets reconstruct the same original signing key. Sheets do not identify the latest version.
Replacing sheets without changing credentials does not revoke earlier sets. Old and new sets
MUST NOT be mixed during reconstruction. Users SHOULD test enough new sheets to unlock the backup
before retiring the old set.

Compatible replacements MAY preserve an existing set bound to the original, including its
`set_id`. They MUST NOT reuse a set bound to an update as though it were bound to the original.
Replacing an earlier set bound to an update MUST create a complete new set to obtain coverage of
the original. Readers MAY still use the earlier sheets when their matching MAIN ciphertext is
available and all original binding rules pass.

Add Files MAY offer sheet creation after the update is published. It MUST call Replace Recovery
Docs for that authenticated version and write the sheets outside the update output folder.
If sheet creation fails, it MUST report that the update is already published and MUST NOT ask the
user to repeat Add Files.

## Rebuild

Rebuild MUST authenticate and reconstruct the selected version, then write its files as a new
standalone document v3 backup in a separate directory. It MUST preserve the passphrase and sealed
state. For an unsealed backup, it MUST also preserve the original signing seed and key.

A sealed backup has no signing seed in its manifest, and Rebuild does not accept separate
signing-key recovery inputs. It MUST generate a new signing key and identify it in the new AUTH.
This does not revoke the old signing key or change the passphrase.

Rebuild MUST use the same automatic compression and standalone preparation as the Add Files
capacity check. It MUST NOT inherit a raw-only payload preference that could break that guarantee.
An earlier oversized file set MAY fail this check, but that failure MUST NOT prevent restoring
its files.

The new ciphertext has a different identity. Rebuild MUST create fresh sheets bound to it. Before
publication, it MUST validate MAIN, AUTH, every generated recovery-sheet payload, and enough sheets
from each new set to recover its secret. The passphrase sheets MUST unlock the new ciphertext;
the signing-key sheets MUST reconstruct its signing key. Ordinary standalone backup creation MUST
perform these same document and sheet checks.

Create backup and Rebuild MUST publish into `backup-<id>` inside the selected destination, where
`<id>` is the new document ID in hexadecimal. The destination is always a parent folder, even if
it does not exist yet. Create backup defaults to the current directory when no parent is selected.
The preview MUST show the child-folder pattern until the ID is known. An existing parent is valid;
an existing child at the final backup path MUST NOT be overwritten.

Users SHOULD restore the rebuilt backup with its new sheets before retiring the source. If they
use expected-version checks, they SHOULD record the new full fingerprint. The previous fingerprint
will not match. This requires no filesystem registry or signed ancestry record.

Rebuild does not revoke old credentials. Changing the passphrase or unsealed signing key, deleting
or renaming files, and recovering from compromise require a new backup and retirement of the
superseded documents.

## Publish output and handle interruptions

Add Files and Rebuild MUST leave source documents unchanged and MUST NOT overwrite an existing
destination. Both MUST use the same authenticated input snapshot that was assessed. They MUST NOT
infer a newer version from a folder or require a persistent lock on the source backup.

Publication follows these steps:

1. Create a private `.staging-*` sibling on the destination filesystem.
2. Render the required documents there.
3. Validate the exact file inventory and contents, then record file names, sizes, and hashes.
4. Check the output against the reviewed input snapshot and expected next index where applicable.
   Recheck the staging directory's identity, recorded files, and absent destination.
5. Flush every staged regular file with `fsync`.
6. Rename the staging directory atomically to the destination on the same filesystem.
7. Flush the parent directory with `fsync` where the platform supports directory flushing.

A failed process MUST NOT leave a partly published destination. There is no transaction journal,
repair command, quarantine, or resume protocol. Abandoned staging directories remain outside the
backup and may be removed only after establishing that no publisher is using them.

Optional layout diagnostics stay outside the update output folder. A diagnostic failure after
publication MUST NOT roll back a successfully published update.
