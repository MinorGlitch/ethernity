# Ethernity Core Format Specification

This document specifies Ethernity's interoperable on-paper and on-disk formats: envelopes,
manifests, frame encoding, QR payloads, fallback text, authenticated extension chains, and replay.

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT", "SHOULD", "SHOULD NOT",
"RECOMMENDED", "NOT RECOMMENDED", "MAY", and "OPTIONAL" in this document are to be interpreted as
described in BCP 14 ([RFC 2119](https://www.rfc-editor.org/rfc/rfc2119),
[RFC 8174](https://www.rfc-editor.org/rfc/rfc8174)) when, and only when, they appear in all capitals.

Scope:
- Standalone root envelope binary container (Version 1)
- Extension envelope binary container (Version 2)
- Manifest structure and file paths
- Frame encoding (QR and fallback)
- Auth and shard payloads
- Encryption (age)
- Passphrase representation (BIP-39)
- Shamir secret sharing
- Path normalization
- Extension envelope authentication, content-addressed selection, and replay

Non-goals:
- CLI UX and UI
- Rendering layout or templates
- Rationale and operational notes (see [Format notes](format_notes.md))
- Canonical publication trees and product workflows (see the
  [v1.2 extension operations and publication profile](extension_publication_profile.md))

## Specification Status

| Component | Serialized version | Release status |
| --- | --- | --- |
| Standalone root envelope and manifest | envelope 1, manifest 1 | Released and supported |
| Frame and AUTH payload | frame 1, AUTH 1 | Released and supported |
| Shard payload | shard 1 and 2 | Version 2 released in Ethernity v1.1; version 1 remains readable |
| Extension envelope and header | envelope 2, header 1 | Normative for Ethernity v1.2.0 |

The Ethernity product version is not serialized into an artifact. The table describes the current
implementation and release history; the numeric format markers below remain the compatibility
authority. The v1.2 [extension operations and publication profile](extension_publication_profile.md)
is normative for implementations that claim that product profile, but its filenames, PDF roles, and
workflow rules do not determine wire identity.

## 1) Primitive Encoding: Unsigned Varint

Lengths and indexes in binary headers MUST be encoded as unsigned varints ("uvarint").

Encoding:
- 7 bits of data per byte, little-endian.
- MSB (0x80) is set on all bytes except the last.
- Values MUST be in unsigned 64-bit range (0 ≤ value ≤ 2^64-1).
- Uvarints MUST use the shortest possible encoding (no overlong forms).

Decoder requirements:
- Decoders MUST reject non-canonical (overlong) uvarints.
- Decoders MUST reject uvarints outside unsigned 64-bit range.

Used for:
- Envelope version, manifest length, payload length
- Frame version, index, total, data length

## 2) Envelope Format (Version 1 Standalone Root)

This section defines the standalone root envelope (`VERSION = 1`). Extension envelopes use
`VERSION = 2` and are specified separately in Section 19.

Constants:
- MAGIC: `0x41 0x59` ("AY")
- VERSION: `1`

Binary layout:
```
MAGIC (2 bytes)
VERSION (uvarint)
MANIFEST_LEN (uvarint)
MANIFEST_BYTES (CBOR)
PAYLOAD_LEN (uvarint)
PAYLOAD_BYTES (stored payload bytes; encoded per manifest payload_codec)
```

Rules:
- MAGIC MUST equal `0x41 0x59`.
- VERSION MUST equal `1`.
- MANIFEST_LEN and PAYLOAD_LEN MUST match the remaining byte boundaries.
- Decoders MUST reject envelopes where VERSION, MANIFEST_LEN, or PAYLOAD_LEN use non-canonical
  uvarint encoding.
- MANIFEST_BYTES MUST be a CBOR-encoded manifest (Section 3).

Encoders MUST encrypt the complete envelope as a single age message (Section 13) and then split the
resulting ciphertext into frames (Section 6) for QR/fallback transport.

## 2.1) Magic & Domain Tags

These constants are used to identify formats or bind signatures:

- Envelope magic: `0x41 0x59` ("AY")
- Frame format constants (magic, version, types): see Section 6.
- Signature domains:
  - AUTH_DOMAIN = ASCII bytes `"ETHERNITY-AUTH-V1"`
  - SHARD_DOMAIN = ASCII bytes `"ETHERNITY-SHARD-V1"`

## 2.2) Common Canonical CBOR Rules

Every object described as canonical CBOR in this specification MUST use deterministic encoding as
defined by RFC 8949 and MUST NOT contain indefinite-length items. A decoder MUST reject a
non-canonical encoding at the binary envelope or frame boundary before signature verification or
semantic validation.

The manifest, AUTH payload, and shard payload are open versioned maps. For each supported version:

- decoders MUST ignore unknown map keys;
- unknown keys are extension data only and MUST NOT affect signature verification, reconstruction
  eligibility, or authenticated/rescue trust labeling;
- encoders SHOULD NOT emit keys that are not defined for that version.

Schemas that explicitly require exact keys, including extension header and body maps, are closed
and MUST reject unknown keys.

## 3) Manifest Format

The manifest MUST be encoded as a CBOR map.

Constants:
- MANIFEST_VERSION = `1`

```
{
  "version": version,       // int, MUST equal MANIFEST_VERSION (1)
  "created": created_at,    // canonical encoder output: int unix epoch seconds
  "sealed": sealed,         // bool
  "seed": signing_seed,     // bytes or null (Ed25519 seed, 32 bytes)
  "input_origin": origin,   // string: "file", "directory", or "mixed"
  "input_roots": roots,     // list[str], directory source leaf labels
  "payload_codec": codec,   // REQUIRED string: "raw" or "gzip"
  "payload_raw_len": n,     // OPTIONAL int, required when codec is "gzip"
  "path_encoding": mode,    // string: "direct" or "prefix_table"
  "path_prefixes": prefixes,// list[str], required when mode is "prefix_table"
  "files": files            // list[file_entry_direct] or list[file_entry_prefix]
}
```

File entry (direct mode):
```
[path, size, sha256, mtime]
```

File entry (prefix-table mode):
```
[prefix_index, suffix, size, sha256, mtime]
```

Manifest requirements (map keys):
- `version`: int == MANIFEST_VERSION (1)
- `created`: encoders SHOULD emit integer Unix epoch seconds as canonical output
- `created`: decoders MAY accept integer or float values
- `sealed`: bool
- `seed`:
  - if `sealed` is true, `seed` MUST be null
  - if `sealed` is false, `seed` MUST be 32 bytes
- `input_origin`: string in `{"file", "directory", "mixed"}`; `"mixed"` indicates payloads
  sourced from more than one logical root label
- `input_roots`: list of non-empty UTF-8 strings, each a manifest-valid leaf label (no `/` or
  `\`, no Unicode General Category `Cc` code points, no `.` or `..` label, no drive-prefix form,
  and no absolute path form)
- cross-field consistency:
  - if `input_origin` is `"file"`, `input_roots` MUST be empty
  - if `input_origin` is `"directory"` or `"mixed"`, `input_roots` MUST be non-empty
- `path_encoding`: string in `{"direct", "prefix_table"}`
- `payload_codec`:
  - required string in `{"raw", "gzip"}`
- `payload_raw_len`:
  - MUST be absent or null when `payload_codec` is `"raw"`
  - MUST be present and a positive int when `payload_codec` is `"gzip"`
  - MUST be ≤ `MAX_DECOMPRESSED_PAYLOAD_BYTES` (Section 17)
  - MUST equal `sum(files[i].size)`
- `path_prefixes`:
  - required when `path_encoding` is `"prefix_table"`
  - MUST be a non-empty list of strings
  - first element MUST be `""`
  - elements MUST be unique
- `files`: list of entries, MUST contain at least one file entry
- The canonical CBOR byte length of the manifest MUST be ≤ `MAX_MANIFEST_CBOR_BYTES` (Section 17).
- The number of file entries MUST be ≤ `MAX_MANIFEST_FILES` (Section 17).
- The manifest uses the open versioned-map rules in Section 2.2.
- Stable v1 profile decoders MUST require `input_origin`, `input_roots`, and `path_encoding`.
- Stable v1 profile decoders MUST require array-based `files` entries and MUST reject map-style
  file-entry manifests as out-of-profile.

File list requirements:
- Encoders MUST reject empty `files` lists at creation time.
- Decoders MUST reject manifests/envelopes with empty `files` lists.

File entry requirements (direct mode):
- `path`: non-empty string
- `size`: non-negative int
- `sha256`: 32 raw bytes (SHA-256 of file contents, not hex)
- `mtime`: int or null

File entry requirements (prefix-table mode):
- `prefix_index`: int in `[0, len(path_prefixes)-1]`
- `suffix`: non-empty string
- `size`: non-negative int
- `sha256`: 32 raw bytes (SHA-256 of file contents, not hex)
- `mtime`: int or null
- reconstructed path is `suffix` when `path_prefixes[prefix_index] == ""`,
  otherwise `path_prefixes[prefix_index] + "/" + suffix`.

`MANIFEST_BYTES` MUST satisfy the common canonical CBOR rules in Section 2.2.

Ordering:
- Encoders MUST compute each file entry ordering key as
  `normalize_path(reconstructed_path(entry))` (Section 16).
- Encoders MUST sort file entries by ordering key in ascending Unicode code point order before
  manifest creation.
- Payload concatenation MUST follow this same ordering key order.

## 4) File Paths

File paths are represented according to `path_encoding`:
- direct mode stores full path in each file entry
- prefix-table mode stores `prefix_index + suffix` and reconstructs full path via `path_prefixes`

Path validation and normalization requirements are defined in Section 16.
`reconstructed_path(entry)` (direct or prefix-table reconstruction) MUST be the path basis for
ordering and payload concatenation (Sections 3 and 5).

## 5) Payload

Define `raw_payload_bytes` as the concatenation of file contents in ascending
`normalize_path(reconstructed_path(entry))` order as defined in Section 3.

The envelope `PAYLOAD_BYTES` storage representation is selected by manifest metadata:
- raw mode:
  - `payload_codec == "raw"`
  - envelope payload bytes are `raw_payload_bytes`
- gzip mode:
  - `payload_codec == "gzip"`
  - envelope payload bytes are gzip-compressed bytes of `raw_payload_bytes`
  - `payload_raw_len` MUST be present and equal `sum(files[i].size)`

Decoder extraction requirements:
- Decoders MUST normalize payload bytes according to `payload_codec` before file slicing.
- For raw mode, decoders MUST require
  `len(PAYLOAD_BYTES) == sum(files[i].size)` before file slicing.
- For gzip mode, decoders MUST reject payloads where decompression emits more than
  `payload_raw_len` bytes.
- For gzip mode, decoders MUST reject payloads where final decompressed length is not exactly
  `payload_raw_len`.
- For gzip mode, decoders MUST require a complete gzip stream (end-of-stream reached).
- For gzip mode, decoders MUST reject payloads with trailing bytes after the gzip stream.
- For gzip mode, decoders MUST reject manifests with `payload_raw_len` greater than
  `MAX_DECOMPRESSED_PAYLOAD_BYTES`.
- For either codec, the normalized payload length MUST equal `sum(files[i].size)`; no bytes may be
  missing or remain after the final file slice.
- Decoders MUST verify each entry's SHA-256 against the corresponding slice of normalized payload
  bytes.

## 6) Frame Format (QR + Fallback)

Constants:
- MAGIC: `0x41 0x50` ("AP")
- VERSION: `1`
- DOC_ID_LEN: 8 bytes
- CRC_LEN: 4 bytes

Frame layout:
```
MAGIC (2 bytes)
VERSION (uvarint)
FRAME_TYPE (1 byte)
DOC_ID (8 bytes)
INDEX (uvarint)
TOTAL (uvarint)
DATA_LEN (uvarint)
DATA (raw)
CRC32 (4 bytes, big-endian)
```

Frame types:
- MAIN_DOCUMENT = 0x44 ("D")
- KEY_DOCUMENT  = 0x4B ("K")
- AUTH          = 0x41 ("A")
- Decoders MUST reject FRAME_TYPE values other than those listed above.

Frame DATA semantics (Version 1):
- For `FRAME_TYPE=MAIN_DOCUMENT`, reassembly of all frames in the group yields the complete age
  ciphertext (Section 13).
- For `FRAME_TYPE=MAIN_DOCUMENT`, each frame DATA length MUST be ≤ `MAX_MAIN_FRAME_DATA_BYTES`
  (Section 17).
- For `FRAME_TYPE=AUTH`, DATA MUST be the canonical CBOR encoding of the Auth payload (Section 8).
- For `FRAME_TYPE=AUTH`, DATA length MUST be ≤ `MAX_AUTH_CBOR_BYTES` (Section 17).
- For `FRAME_TYPE=KEY_DOCUMENT`, DATA MUST be the canonical CBOR encoding of the Shard payload
  (Section 9).
- For `FRAME_TYPE=KEY_DOCUMENT`, DATA length MUST be ≤ `MAX_SHARD_CBOR_BYTES` (Section 17).

CRC:
- CRC32 is computed over all bytes before the CRC field.
- CRC32 algorithm is CRC-32/ISO-HDLC (PKZIP / IEEE 802.3): polynomial 0x04C11DB7
  (reflected 0xEDB88320), init 0xFFFFFFFF, refin=true, refout=true, xorout=0xFFFFFFFF.

INDEX/TOTAL semantics:
- INDEX is 0-based and MUST satisfy 0 ≤ INDEX < TOTAL.
- TOTAL MUST be ≥ 1.
- For `FRAME_TYPE=MAIN_DOCUMENT`, TOTAL MUST be ≤ `MAX_MAIN_FRAME_TOTAL` (Section 17).
- Decoders MUST reject frames where VERSION, INDEX, TOTAL, or DATA_LEN use non-canonical uvarint
  encoding.

Frame reassembly:
- For `FRAME_TYPE=MAIN_DOCUMENT`, frames MAY be provided out of order; decoders MUST accept
  out-of-order frames.
- `MAIN_DOCUMENT` frames MUST be grouped by DOC_ID and FRAME_TYPE; frames from different
  documents MUST NOT be combined in the same reassembly.
- Within a `MAIN_DOCUMENT` reassembly group, all frames MUST have the same VERSION and TOTAL.
- `MAIN_DOCUMENT` reassembly concatenates DATA in ascending INDEX order
  (INDEX 0, 1, 2, ... TOTAL-1).
- Decoders MUST reject incomplete `MAIN_DOCUMENT` frame sets (missing any INDEX).
- Decoders MUST reject reassembled MAIN ciphertext larger than `MAX_CIPHERTEXT_BYTES` (Section 17).
- Duplicate `MAIN_DOCUMENT` frames (same DOC_ID + FRAME_TYPE + INDEX):
  - If TOTAL and DATA are identical, decoders SHOULD ignore the duplicate.
  - If TOTAL or DATA differs, decoders MUST reject as conflicting duplicates.
- `AUTH` and `KEY_DOCUMENT` frames are independent single-frame payload units and MUST be decoded
  individually. They are not part of multi-frame reassembly groups.

Single-frame payloads (Version 1):
- AUTH and KEY_DOCUMENT payloads MUST be encoded as a single frame (frame index=0, frame total=1).
- Repeated copies of an AUTH frame are handled by the cardinality rules in Section 8.
- Multiple `KEY_DOCUMENT` frames with the same DOC_ID are valid and represent distinct shard
  payloads.

## 7) Document Identifiers

Definitions:
- `doc_hash` = BLAKE2b-256(ciphertext) (unkeyed BLAKE2b with 32-byte digest)
- `doc_id` = first 8 bytes of `doc_hash`

`doc_id` is stored in every frame.
`doc_hash` is signed and embedded in the auth/shard payloads.

Binding requirements:
- Decoders MUST derive `doc_hash` and `doc_id` from recovered MAIN ciphertext before accepting
  associated AUTH/KEY payloads.
- Any associated AUTH or KEY frame MUST have frame `DOC_ID == doc_id`.
- Auth payload `hash` and shard payload `hash` MUST equal `doc_hash`.
- In authenticated mode, decoders MUST treat any mismatch in these bindings as fatal and reject
  recovery.
- In rescue mode (Section 7.1), decoders MAY ignore mismatched AUTH payloads and continue
  unauthenticated recovery of MAIN ciphertext, but MUST reject mismatched KEY payloads used for
  passphrase reconstruction.

### 7.1) Recovery Verification Modes

Version 1 defines two decoder operation modes:

- Authenticated mode (default):
  - Decoders MUST enforce signature verification requirements in Sections 8 and 9.
  - Missing/invalid required authentication material MUST be treated as fatal.
- Rescue mode (explicit operator override only):
  - Decoders MAY continue recovery when AUTH is missing, malformed, or fails signature verification.
  - Decoders MAY continue recovery when shard signatures fail verification, but only if all
    non-signature shard validation and consistency checks still pass.
  - Decoders MUST still enforce all non-signature structural checks (framing, bounds, canonical
    CBOR, shard consistency).
  - Decoders MUST clearly label the result as unauthenticated and MUST NOT report auth as verified.

Read-only inspection and projection surfaces MAY be stricter than rescue-mode recovery. They MAY
refuse unauthenticated, authority-mismatched, or partially decoded extension-chain previews instead
of presenting a best-effort state, even when explicit rescue-mode recovery could still recover root
MAIN ciphertext.

### 7.2) Trusted Signing Authority

For an authenticated standalone root, the verified AUTH payload establishes `root_sign_pub`:

1. derive `doc_hash` and `doc_id` from the recovered MAIN ciphertext;
2. select the single distinct AUTH frame required by Section 8;
3. verify its frame and payload bindings and its Ed25519 signature; and
4. set `root_sign_pub` to that verified AUTH payload's `pub` value.

If the recovered root manifest is unsealed, decoders MUST derive the Ed25519 public key from the
32-byte manifest `seed` as defined by RFC 8032 and MUST require it to equal `root_sign_pub`. If the
manifest is sealed, `seed` is null and no manifest-seed comparison is possible; the verified AUTH
`pub` remains the root signing authority.

In authenticated mode:

- every shard used for the root MUST have `pub == root_sign_pub` in addition to the bindings in
  Section 7 and the signature checks in Section 9;
- every extension AUTH payload MUST have `pub == root_sign_pub` in addition to its own ciphertext
  binding and signature verification; and
- a reconstructed `signing-seed` secret MUST derive exactly `root_sign_pub` before it is used as
  signing authority.

An equality failure in this subsection is fatal in authenticated mode. Rescue mode MAY bypass a
signature or authority check only as permitted by Section 7.1 and MUST NOT label the resulting
authority or recovery as authenticated.

## 8) Auth Payload (FrameType.AUTH data)

Auth payload MUST be a CBOR map:

Constants:
- AUTH_VERSION = `1`

```
{
  "version": version,
  "hash": doc_hash,
  "pub": sign_pub,
  "sig": signature
}
```

Requirements:
- `version`: int == AUTH_VERSION (1)
- `hash`: 32 bytes
- `pub`: 32 bytes (Ed25519 public key)
- `sig`: 64 bytes Ed25519 signature
- AUTH uses the open versioned-map and canonical CBOR rules in Section 2.2.

Signature domain:
- Let `signed_auth_payload` be a CBOR map containing exactly `version`, `hash`, and `pub`.
- Message is `AUTH_DOMAIN + canonical_cbor(signed_auth_payload)`
- AUTH_DOMAIN is defined in Section 2.1.

Verification requirements:
- In authenticated mode, decoders MUST verify `sig` as an Ed25519 signature over
  `AUTH_DOMAIN + canonical_cbor(signed_auth_payload)`.
- In authenticated mode, decoders MUST reject AUTH payloads with invalid signatures.
- Signature verification bypass is permitted only in rescue mode (Section 7.1).
- In rescue mode, decoders MAY ignore missing/invalid AUTH payloads and continue unauthenticated.

AUTH cardinality and duplicate handling:

- Transport input MAY contain repeated copies of the same AUTH frame.
- Decoders MUST collapse copies whose complete decoded frame values are identical.
- Two AUTH frames with the same `DOC_ID` that differ in `VERSION`, `INDEX`, `TOTAL`, or `DATA` are
  conflicting, and decoders MUST reject them rather than choose between them.
- After identical-copy deduplication, authenticated recovery of a standalone root or extension
  MUST have exactly one AUTH frame for that document.
- Rescue mode MAY continue with no usable AUTH frame, but it MUST NOT resolve multiple distinct
  AUTH frames by trusting one of them.

## 9) Shard Payload (FrameType.KEY_DOCUMENT data)

Shard payload MUST be a CBOR map:

Constants:
- SHARD_VERSION = `2`
- LEGACY_SHARD_VERSION = `1`
- SHARD_SET_ID_LEN = `16`

```
{
  "version": version,
  "type": key_type,
  "threshold": threshold,
  "share_count": shares,
  "share_index": index,
  "length": secret_len,
  "share": share,
  "hash": doc_hash,
  "pub": sign_pub,
  "set_id": shard_set_id,
  "sig": signature
}
```

Requirements:
- `version`: int == 1 or 2
- `type`: "passphrase" or "signing-seed"
- `threshold`/`share_count`/`share_index`/`length`: positive ints
- `share`: bytes
- `hash`: 32 bytes
- `pub`: 32 bytes
- `set_id`: 16 bytes when `version == 2`
- `sig`: 64 bytes
- Shard payloads use the open versioned-map rules in Section 2.2.

Validation rules:
- `threshold`: MUST satisfy 1 ≤ threshold ≤ share_count
- `share_count`: MUST satisfy share_count ≥ 1
- `share_index`: MUST satisfy 1 ≤ share_index ≤ share_count
- `share`/`length` consistency:
  - `share` length MUST be a multiple of 16 bytes.
  - `length` MUST satisfy 1 ≤ length ≤ len(share).
  - len(share) MUST equal `ceil(length/16) * 16`.
- Type-specific length constraints:
  - If `type == "signing-seed"`, `length` MUST equal 32.
- Version-specific constraints:
  - If `version == 2`, `set_id` MUST be present and exactly 16 bytes.
  - If `version == 1`, `set_id` MUST be absent or ignored for compatibility.

Decoders MUST reject shard payloads that violate these bounds.

Shard payload DATA MUST satisfy the common canonical CBOR rules in Section 2.2.

Signature domain:
- For `version == 1`, let `signed_shard_payload` be a CBOR map containing exactly:
  `version`, `type`, `threshold`, `share_count`, `share_index`, `length`, `share`, `hash`, and
  `pub`.
- For `version == 2`, let `signed_shard_payload` be a CBOR map containing exactly:
  `version`, `type`, `threshold`, `share_count`, `share_index`, `length`, `share`, `hash`, `pub`,
  and `set_id`.
- Message is `SHARD_DOMAIN + canonical_cbor(signed_shard_payload)`
- SHARD_DOMAIN is defined in Section 2.1.

Verification requirements:
- In authenticated mode, decoders MUST verify `sig` as an Ed25519 signature over
  `SHARD_DOMAIN + canonical_cbor(signed_shard_payload)`.
- In authenticated mode, decoders MUST reject shard payloads with invalid signatures.
- In authenticated mode, each shard used for a root or extension document MUST have `pub` equal to
  the verified root signing authority established in Section 7.2.
- Signature verification bypass is permitted only in rescue mode (Section 7.1).
- In rescue mode, decoders MAY proceed without shard signature verification, but MUST still enforce
  shard structural/binding/consistency requirements before using shards for reconstruction.
- In a shard reconstruction set, all shard payloads MUST share the same
  `hash`, `pub`, `type`, `threshold`, and `share_count`.
- In a shard reconstruction set, all shard payloads MUST also share the same `version`.
- If `version == 2`, all shard payloads in the reconstruction set MUST share the same `set_id`.
- Duplicate `share_index` handling:
  - If the duplicated `share` bytes are identical, decoders SHOULD ignore the duplicate.
  - If the duplicated `share` bytes differ, decoders MUST reject.
- Set-level consistency requirements for `hash`, `pub`, `type`, `threshold`, and `share_count`
  apply to the deduplicated reconstruction set after duplicate `share_index` resolution.
- For `version == 2`, a mismatched `set_id` MUST be treated as an incompatible shard-set error even
  when the input contains exactly `threshold` shares.
- Decoders MAY perform stricter validation earlier (for example, rejecting duplicate entries that
  disagree on consistency fields even when `share` bytes match).
- Decoders MAY accept legacy `version == 1` shard payloads for compatibility. Legacy shards do not
  carry `set_id`, so mixed exact-quorum shard sets are only detectably incompatible when additional
  shares permit cross-checking.

A recovery set MAY contain multiple `KEY_DOCUMENT` frames for the same DOC_ID.
Each shard payload MUST be encoded as a single frame (frame index=0, frame total=1).

## 10) QR Payload Transport

Version 1 supports exactly two QR transport codecs for frame bytes:
- `raw`: QR payload is the raw frame bytes.
- `base64`: QR payload text is unpadded base64.

No envelope or manifest field records the QR transport codec.

Encoding:
- raw mode:
  - Emit frame bytes unchanged.
- base64 mode:
  - Base64 encode the raw frame bytes.
  - Strip trailing "=" padding characters.

Decoding:
- Byte scan inputs:
  - Decoders SHOULD attempt direct frame decode from raw bytes first.
  - If raw decode fails, decoders MAY interpret bytes as text and apply strict base64 decode.
- Text inputs (for example payload files/stdin/manual paste):
  - After whitespace removal, payload text MUST NOT contain "=" characters.
  - Restore padding to a multiple of 4.
  - Base64 decode with validation.
  - After decode, payload text MUST be canonical unpadded base64: if `normalized` is payload text
    after whitespace removal and `decoded` is decoded bytes, decoders MUST require
    `normalized == base64_unpadded(decoded)` and MUST reject otherwise.
  - After whitespace removal, payload text length MUST be ≤ `MAX_QR_PAYLOAD_CHARS` (Section 17).

Decoders MUST ignore whitespace in text payloads.
Encoders and decoders MUST NOT negotiate or auto-detect QR payload codecs beyond `raw` and
`base64` in Version 1.

## 11) Fallback Text Encoding

Fallback text MUST encode the raw frame bytes with z-base-32.

Encoding:
- Alphabet: `ybndrfg8ejkmcpqxot1uwisza345h769`
- Encoders MAY insert arbitrary whitespace and dashes (`-`) for readability.

Decoding:
- Recovery text sources (files/stdin) MUST be rejected if byte length exceeds
  `MAX_RECOVERY_TEXT_BYTES` (Section 17).
- For each fallback section, decoders MUST apply the following deterministic filtering algorithm:
  1. Split section text into lines using `\n`, `\r\n`, or `\r`.
  2. For each line, if a leading rendered line label matches `[0-9]{1,4}\.` followed by optional
     whitespace, decoders MUST remove exactly one such prefix. A second prefix, and any undotted
     digit prefix, MUST NOT be treated as a rendered line label.
  3. Remove all Unicode whitespace code points and ASCII dashes (`-`).
  4. If the resulting string is empty, discard it.
  5. Every remaining code point MUST be ASCII and MUST belong to the z-base-32 alphabet
     (`ybndrfg8ejkmcpqxot1uwisza345h769`) after ASCII `A-Z` case folding. Decoders MUST reject
     non-ASCII lookalikes or Unicode compatibility characters before case normalization.
  6. Normalize ASCII uppercase characters to lowercase and append the remaining string to the
     filtered-line list.
- `MAX_FALLBACK_LINES` counts the number of filtered lines after Step 6.
- `MAX_FALLBACK_NORMALIZED_CHARS` counts the sum of lengths of all filtered lines after Step 6.
- Decoders MUST reject any fallback section that exceeds either bound.
- Decoders MUST decode each filtered line list by concatenating filtered lines in order and applying
  z-base-32 decoding.
- Decoders MUST reject non-canonical z-base-32 text (for example non-zero unused tail bits);
  equivalently, after normalization/filtering, concatenated text MUST equal
  `encode_zbase32(decode_zbase32(text))`.

### 11.1) Reference

z-base-32 (human-oriented base-32):
https://philzimmermann.com/docs/human-oriented-base-32-encoding.txt

## 12) Version Markers

Version markers:
- Standalone root envelope: MAGIC + VERSION
- Extension envelope: MAGIC + VERSION
- Manifest: MANIFEST_VERSION
- Frames: MAGIC + VERSION
- Auth: AUTH_VERSION
- Shards: SHARD_VERSION

Current version values:
- Standalone root Envelope VERSION = `1`
- Extension Envelope VERSION = `2`
- Extension header schema VERSION = `1`
- Frame VERSION = `1`
- MANIFEST_VERSION = `1`
- AUTH_VERSION = `1`
- SHARD_VERSION = `2`

Extension chain metadata constants:
- CHAIN_ID_PERSONALIZATION = `"ETHERNITY-CHAIN-V1"` encoded as ASCII bytes

### 12.1) Standalone v1 Profile Baseline Contract

These requirements preserve the released standalone v1 profile while extension envelope v2 remains
a separate format marker.

Stable v1 profile requirements:
- Envelope/frame magic constants, frame types, and version constants remain unchanged from
  Version 1.
- Stable v1 decoders MUST require manifest keys `input_origin`, `input_roots`, and `path_encoding`.
- Stable v1 decoders MUST require array-based `files` entries and MUST reject map-style file-entry
  manifests as out-of-profile.
- Manifest/auth/shard unknown-key handling is extension-only as defined in Sections 3, 8, and 9.
- Frame types are closed for v1; decoders MUST reject frame types outside Section 6.
- QR payload transport codecs in v1 are limited to `raw` and unpadded `base64`; runtime/profile
  negotiation of any other codec is not permitted.
- Parsing is fail-closed: malformed canonical encodings or invalid structural/binding content MUST
  be rejected.

## 13) Encryption

Ciphertext MUST use the age encryption format (https://age-encryption.org/v1).

### 13.1) Encryption Process

Input: Envelope binary (MAGIC + VERSION + MANIFEST + PAYLOAD)
Output: age ciphertext

Encoders MUST encrypt the complete envelope as a single age message.

### 13.2) Recipient Type

Encoders MUST use passphrase recipients:
- Recipient type: `scrypt` (age-encryption.org/v1/scrypt)
- Scrypt parameters (work factor, salt, etc.) are determined by the age recipient stanza.

Identity-based recipients (age X25519 keys) MUST NOT be used.

### 13.3) Ciphertext Handling

After encryption:
- `doc_hash` and `doc_id` MUST be computed from the ciphertext as specified in Section 7.

The ciphertext MUST then be framed for QR/fallback output.

### 13.4) Decryption

Decryptors MUST supply the exact passphrase string used at encryption time.

### 13.5) Reference

Full age format specification: https://age-encryption.org/v1

## 14) Passphrase Representation

The age scrypt passphrase is a Unicode string provided out of band. This section defines a BIP-39
mnemonic profile for passphrases.

### 14.1) Parameters

- Word list: BIP-39 English (2048 words)
- Word count: 12, 15, 18, 21, or 24
- Entropy: 128 (12 words), 160 (15), 192 (18), 224 (21), or 256 bits (24)
- Checksum: Included per BIP-39 (final word encodes checksum)

### 14.2) Mnemonic as Passphrase

When a BIP-39 mnemonic phrase is used as the age encryption passphrase:
- Words MUST be separated by a single ASCII space (0x20) with no leading/trailing whitespace.
- Words MUST be lowercase as generated from the BIP-39 word list.
- The mnemonic string MUST be provided directly to the age scrypt recipient (no additional KDF).

### 14.3) Sharding

For `type: "passphrase"` shard payloads, the sharded secret MUST be the UTF-8 encoding of the
passphrase string:
- Shard `type`: `"passphrase"`
- Input: UTF-8 encoded passphrase string

Reassembled shares produce the original passphrase string, ready for use.

### 14.4) Non-BIP-39 Passphrase Handling Guidance

For passphrases that are not BIP-39 mnemonics:
- Producers SHOULD use a consistent Unicode normalization form (NFC is RECOMMENDED).
- Operators SHOULD treat passphrase entry as exact string material (no implicit trimming,
  case-folding, or rewriting).

### 14.5) Reference

BIP-39 specification: https://github.com/bitcoin/bips/blob/master/bip-0039.mediawiki

## 15) Shamir Secret Sharing

Shard payloads (Section 9) use Shamir's Secret Sharing for threshold-based reconstruction of
passphrases and signing seeds. Share generation and reconstruction MUST follow this section.

### 15.1) Field Parameters

- Field: GF(2^128)
- Irreducible polynomial: x^128 + x^7 + x^2 + x + 1 (0x100000000000000000000000000000087)
- Arithmetic: Polynomial operations over GF(2)

Field representation and serialization:

- Represent a field element as an unsigned integer `e` in `0..2^128-1`.
- Integer bit `i` is the coefficient of `x^i`; addition is integer bitwise XOR.
- Multiplication is carryless polynomial multiplication followed by reduction modulo
  `x^128 + x^7 + x^2 + x + 1`.
- Serialize an element as exactly 16 bytes in unsigned big-endian order, and parse a 16-byte block
  as an unsigned big-endian integer. Consequently, the low bit of the final byte is the coefficient
  of `x^0`, and the high bit of the first byte is the coefficient of `x^127`.
- Map `share_index = i` directly to the field element whose integer value is `i`; indices are not
  hashed, offset, or encoded as a separate field representation.

### 15.2) Share Generation

Input:
- Secret: non-empty byte string
- Threshold (t): minimum shares required for reconstruction
- Total (n): total shares to generate

Process:
- Secret is chunked into 16-byte blocks
- Each secret block is parsed as the constant field element `s` using Section 15.1.
- Shamir is applied independently to each block using
  `f(x) = s + a_1*x + ... + a_(t-1)*x^(t-1)`.
- For each block polynomial, coefficients (except the secret constant term) MUST be generated with
  a cryptographically secure random number generator and sampled uniformly over GF(2^128).
- Encoders MUST NOT derive Shamir coefficients from predictable or deterministic non-cryptographic
  sources (for example timestamps, counters, or process IDs).
- Padding: if the final block is shorter than 16 bytes, it is right-padded with zero bytes (0x00)
  to exactly 16 bytes.
- The original unpadded secret length is stored in the shard payload field `length`.

Output:
- For each `share_index = i`, evaluate every block polynomial at the field element `i`, serialize
  each result as specified in Section 15.1, and concatenate the serialized results in original
  block order.
- The output is `n` shares with indices 1 through `n`, inclusive.

### 15.3) Share Format

Each share in the shard payload contains:
- `share_index`: 1 ≤ share_index ≤ share_count
- `share`: bytes (same length as the padded secret; `ceil(length/16) * 16`)
- `length`: original secret length in bytes (used to truncate the recovered padded secret)
- `set_id`: a shard-set identifier when `version == 2`

Decoders MUST reject shard payloads where `share` and `length` are inconsistent.

### 15.4) Reconstruction

Input:
- At least t shares after applying duplicate handling rules from Section 9
- Reconstruction uses the deduplicated set from Section 9.
- Decoders MAY use any subset of at least `threshold` distinct shares from that set (including all
  available shares).
- For `version == 2`, exact-threshold reconstruction sets MUST share the same `set_id` before
  reconstruction proceeds.

Process:
- Lagrange interpolation over GF(2^128)
- Applied per 16-byte block
- Result truncated to original `length`

For distinct input points `(x_j, y_j)`, interpolation at `x` is:

```text
f(x) = sum_j y_j * product_(m != j) ((x + x_m) / (x_j + x_m))
```

Addition and subtraction are both XOR in characteristic two. Reconstruction of the secret evaluates
this expression at `x = 0`, serializes each recovered block per Section 15.1, concatenates the
blocks, and then truncates to `length`.

Output:
- Original secret bytes

### 15.5) Constraints

- Maximum index: 255
- Minimum threshold: 1
- Maximum threshold: share_count
- Maximum shares: 255

Validation:
- 1 ≤ threshold ≤ share_count ≤ 255
- 1 ≤ share_index ≤ share_count
- After applying duplicate handling rules from Section 9, all indices in the effective
  reconstruction set MUST be distinct

Encoders MUST NOT generate and decoders MUST reject shard parameters outside these bounds.

### 15.6) Arithmetic Conformance Vector

This fixed-coefficient vector tests field mapping and serialization only; production encoders MUST
still generate coefficients randomly as required by Section 15.2.

```text
threshold = 2
secret block = 00000000000000000000000000000000
a_1         = 80000000000000000000000000000000
share 1     = 80000000000000000000000000000000
share 2     = 00000000000000000000000000000087
```

Both shares MUST reconstruct the all-zero secret block. The second share follows because
`x^128 mod (x^128 + x^7 + x^2 + x + 1) = x^7 + x^2 + x + 1`.

### 15.7) Reference

- Shamir, Adi. "How to share a secret." Communications of the ACM 22.11 (1979): 612-613.

## 16) Path Normalization

### 16.1) Unicode Normalization

All file paths MUST be normalized to Unicode NFC (Canonical Decomposition, followed by Canonical
Composition) form.

Requirements:
- Paths MUST be normalized to NFC before storage in manifest
- Paths MUST be normalized to NFC before any comparison operation
- Paths that are not valid UTF-8 MUST be rejected
- U+002F (`/`) is the only path separator. U+005C (`\`) MUST be rejected wherever it occurs.
- Paths MUST NOT contain a code point in Unicode General Category `Cc`.
- Paths MUST be relative (no leading `/`)
- Paths MUST NOT start with a drive-letter prefix (`A:` through `Z:` or `a:` through `z:`)
- Paths MUST NOT contain empty segments
- Paths MUST NOT contain `.` or `..` segments
- Path UTF-8 byte length MUST be ≤ `MAX_PATH_BYTES` (Section 17)

Manifest-level path consistency:
- Paths that differ only by Unicode normalization are considered identical; duplicates MUST be
  rejected

### 16.2) Normalization Function

Let `normalize_path(path)` return Unicode NFC normalization of `path`.

Let `reconstructed_path(entry)` be:
- direct mode: the entry `path`
- prefix-table mode: `suffix` when `path_prefixes[prefix_index] == ""`, otherwise
  `path_prefixes[prefix_index] + "/" + suffix`

Let `ordering_path(entry)` be `normalize_path(reconstructed_path(entry))`.

### 16.3) Reference

Unicode Normalization Forms: https://unicode.org/reports/tr15/

## 17) Resource Bounds

This section defines mandatory Version 1 and root-plus-extension recovery resource bounds.

Encoders MUST NOT emit artifacts that exceed these bounds.
Decoders MUST reject inputs that exceed these bounds.
For `MAX_CIPHERTEXT_BYTES`, the bound applies to the final encrypted ciphertext transport size.
Encoders MAY accept larger pre-encryption inputs when compression/encryption still produces
ciphertext within this ceiling.
- `MAX_MAIN_FRAME_DATA_BYTES` bounds each MAIN frame `DATA` field independently.
- `MAX_CIPHERTEXT_BYTES` bounds the reassembled MAIN payload bytes.
- Both constraints apply; frame-level limits do not relax the reassembled ciphertext ceiling.

Constants:
- `MAX_CIPHERTEXT_BYTES = 1_048_576`
- `MAX_MAIN_FRAME_DATA_BYTES = 1_048_576`
- `MAX_MAIN_FRAME_TOTAL = 4_096`
- `MAX_QR_PAYLOAD_CHARS = 3_072`
- `MAX_AUTH_CBOR_BYTES = 512`
- `MAX_SHARD_CBOR_BYTES = 2_048`
- `MAX_MANIFEST_CBOR_BYTES = 1_048_576`
- `MAX_MANIFEST_FILES = 2_048`
- `MAX_PATH_BYTES = 512`
- `MAX_FALLBACK_NORMALIZED_CHARS = 2_000_000`
- `MAX_FALLBACK_LINES = 50_000`
- `MAX_RECOVERY_TEXT_BYTES = 10_485_760`
- `MAX_DECOMPRESSED_PAYLOAD_BYTES = 67_108_864` (64 MiB)
- `MAX_JS_SAFE_INTEGER = 9_007_199_254_740_991`
- `MAX_RECOVERY_DOCUMENTS = 128` (one root plus at most 127 extensions)
- `MAX_EXTENSION_INDEX = 127`
- `MAX_RECOVERY_CIPHERTEXT_BYTES = 67_108_864` (64 MiB across the complete chain)
- `MAX_RECOVERY_DECODED_CHUNK_BYTES = 268_435_456` (256 MiB across extension inline chunks)

## 18) Normative Conformance Appendix

This appendix is normative. Implementations that claim conformance with the current core format
specification MUST satisfy all requirements in this section for the format versions they support.

### 18.1) Required Decoder Validation Order

Decoders MUST apply validation in this order:
1. Parse framing/envelope boundaries and reject non-canonical uvarints at each decode boundary.
2. Enforce resource bounds (Section 17) before unbounded allocation or reconstruction.
3. Decode CBOR payloads and reject non-canonical CBOR at manifest/auth/shard boundaries.
4. Apply structural validation for manifest/auth/shard fields and cross-field constraints.
5. Apply binding and consistency checks (`doc_id`/`doc_hash`, shard set consistency, payload hash
   checks).
6. Apply signature-policy checks according to authenticated or rescue mode.
7. Apply the signing-authority equality checks in Section 7.2.
8. Emit trust labeling that reflects the applied mode and verification outcome.

### 18.2) Minimum Must-Pass Positive Scenarios

A conforming decoder MUST accept at least these scenarios:
1. A stable v1 envelope with required manifest keys, array-based file entries, canonical CBOR,
   canonical uvarints, and payload ordering by `ordering_path(entry)`.
2. A valid AUTH frame with canonical CBOR, valid `DOC_ID` binding, and a valid signature in
   authenticated mode.
3. A valid shard reconstruction set with canonical CBOR payloads, consistent set fields, sufficient
   threshold, and valid signatures in authenticated mode.
4. A valid QR payload that decodes to a valid frame using either:
   - raw frame bytes transport, or
   - unpadded base64 text transport (with optional whitespace only).
5. Equivalent fallback text with and without one dotted rendered line label per payload line.
6. Redundant, identical copies of the one AUTH frame, treated as one distinct AUTH frame.
7. The GF(2^128) arithmetic vector in Section 15.6.
8. A raw payload whose byte length equals the sum of manifest file sizes, including an all-empty
   file set represented in raw mode.

### 18.3) Minimum Must-Reject Negative Scenarios

A conforming decoder MUST reject at least these scenarios:
1. Manifests that use map-style file entries (out of stable v1 profile).
2. Envelope or frame headers containing non-canonical uvarints.
3. Manifest, AUTH, or shard CBOR payloads that are non-canonical or use indefinite-length items.
4. Inputs where unknown manifest/auth/shard keys are used to alter signature verification decisions,
   key reconstruction eligibility, or authenticated/rescue trust labeling.
5. Fallback sections whose filtering/counting outcome is nondeterministic (for example,
   locale-dependent whitespace classification or implementation-defined line splitting) or that
   exceed `MAX_FALLBACK_LINES` or `MAX_FALLBACK_NORMALIZED_CHARS` under Section 11 algorithm.
6. AUTH or shard payloads whose `hash` does not bind to recovered ciphertext `doc_hash`, or whose
   frame `DOC_ID` does not match derived `doc_id`.
7. QR payload text that contains `=` after whitespace removal or otherwise violates unpadded-base64
   strictness in Section 10.
8. Gzip-coded envelope payloads that include trailing bytes after a valid gzip stream.
9. Manifest paths that start with a drive-letter prefix (`A:` through `Z:` or `a:` through `z:`).
10. Raw payloads whose length differs from the sum of manifest file sizes.
11. Manifest paths containing U+005C (`\`) or a Unicode General Category `Cc` code point.
12. Two distinct AUTH frames for one document, including two independently self-signed payloads.
13. In authenticated mode, any mismatch among an unsealed manifest seed's derived public key, the
    verified root AUTH `pub`, a used shard `pub`, an extension AUTH `pub`, or the public key derived
    from a reconstructed signing seed.
14. A fallback payload line with two dotted rendered line-label prefixes; only the first prefix is
    removable under Section 11.

## 19) Extension Chain Format (Extension Envelope)

The extension envelope is an authenticated append-only document that lives beside a standalone root
backup. The root backup remains a Version 1 envelope. Each extension is a separately encrypted MAIN
document whose ciphertext has its own `doc_hash` and `doc_id` under Section 7. On the wire, the
extension envelope uses outer envelope `VERSION = 2`.

Extension authentication is carried beside the ciphertext, not inside the encrypted extension
header/body. After identical-copy deduplication under Section 8, extension recovery MUST verify
exactly one distinct AUTH payload bound to the extension ciphertext `doc_hash` and signed by the
root signing authority established in Section 7.2. The core format assigns no filename or physical
carrier role to that AUTH payload.

### 19.1) Extension Envelope Binary Layout

Constants:
- MAGIC: `0x41 0x59` ("AY")
- VERSION: `2`

Binary layout:
```text
MAGIC (2 bytes)
VERSION (uvarint)
HEADER_LEN (uvarint)
HEADER_BYTES (canonical CBOR map; Section 19.2)
BODY_LEN (uvarint)
BODY_BYTES (canonical CBOR map; Section 19.3)
```

Rules:
- MAGIC MUST equal `0x41 0x59`.
- VERSION MUST equal `2`.
- `HEADER_LEN` and `BODY_LEN` MUST use canonical uvarints and MUST match byte boundaries exactly.
- `HEADER_BYTES` and `BODY_BYTES` MUST satisfy the canonical CBOR rules in Section 2.2.
- Decoders MUST reject non-canonical uvarints, truncated header/body sections, or extra bytes after
  `BODY_BYTES`.
- `HEADER_BYTES` and `BODY_BYTES` MUST each be `<= MAX_MANIFEST_CBOR_BYTES` (Section 17).

As with Version 1, encoders MUST encrypt the complete extension envelope as a single age message
and then frame the resulting ciphertext according to Section 6.

A conforming authenticated extension input MUST provide exactly one distinct AUTH frame for its
ciphertext after Section 8 deduplication:
- the AUTH payload MUST bind to the extension ciphertext `doc_hash`
- the AUTH payload MUST be encoded as a single-frame AUTH payload
- the AUTH `pub` and signature MUST use the root signing authority established in Section 7.2
- AUTH transport MAY share a physical carrier with MAIN frames; physical artifact roles are defined
  by the [extension operations and publication profile](extension_publication_profile.md)

### 19.2) Extension Header

The extension header MUST be a CBOR map with exactly these integer keys:

```text
1 -> version
2 -> index
4 -> parent_doc_hash
5 -> root_doc_hash
7 -> created_at
10 -> chunking
11 -> input_origin
12 -> input_roots
```

Requirements:
- `version`: int == `1`
- `index`: int in `1..MAX_EXTENSION_INDEX`
- `parent_doc_hash`: 32 bytes
- `root_doc_hash`: 32 bytes
- `created_at`: int
- `chunking`: list `[algorithm_id, target_size, min_size, max_size]`
  - all values MUST be positive ints
  - `target_size`, `min_size`, and `max_size` MUST each be
    `>= 4096` and
    `<= MAX_DECOMPRESSED_PAYLOAD_BYTES`
  - `min_size <= target_size <= max_size`
  - `algorithm_id == 1` identifies the extension-envelope FastCDC-style content-defined chunking
    profile
  - encoders and replay logic MUST honor the full profile; they MUST NOT treat `target_size` as a
    fixed-size slicing width
- `input_origin`: `"file"`, `"directory"`, or `"mixed"`
- `input_roots`:
  - each root MUST be a non-empty UTF-8 leaf label that passes manifest path validation as a single
    segment
  - roots are NFC-normalized but otherwise preserved exactly; decoders MUST NOT trim leading or
    trailing whitespace
  - roots MUST NOT contain `/` or `\`
  - roots MUST NOT contain Unicode General Category `Cc` code points, MUST NOT be `.` or `..`, MUST
    NOT use absolute path syntax, and MUST NOT use drive-prefix syntax
  - MUST be empty when `input_origin == "file"`
  - MUST be non-empty when `input_origin` is `"directory"` or `"mixed"`

Unknown header keys MUST be rejected.
Header keys `3`, `6`, `8`, and `9` are not part of the Version 2 extension schema and MUST be
rejected.

Every integer encoded in a Version 2 extension header or body MUST be within
`-MAX_JS_SAFE_INTEGER..MAX_JS_SAFE_INTEGER`, inclusive. A narrower field-specific bound takes
precedence. This includes timestamps and mtimes; non-negative sizes and chunk lengths remain subject
to their smaller resource bounds.

### 19.3) Extension Body

The extension body MUST be a CBOR map with exactly these integer keys:

```text
1 -> files
2 -> chunks
```

`files` MUST be a non-empty array of file recipes. `chunks` MUST be an array of newly introduced
chunk records and MAY be empty. Each chunk record in `chunks` MUST be referenced by at least one
file recipe in the same extension body.

Unknown body keys MUST be rejected.

#### 19.3.1) File Recipe

Each file recipe MUST be:

```text
[path, size, sha256, mtime, chunk_refs]
```

Requirements:
- `path`: normalized manifest path per Section 16
- `size`: non-negative int
- `sha256`: 32 bytes
- `mtime`: int or null
- `chunk_refs`: array of chunk references
  - zero-length files MUST have an empty `chunk_refs` array
  - non-empty files MUST have a non-empty `chunk_refs` array
  - the sum of `chunk_ref.uncompressed_len` values MUST equal `size`

Version 2 extension file recipes only describe complete file content for paths carried by the
extension. They MUST NOT be interpreted as delete, rename, or tombstone records.

Each chunk reference MUST be:

```text
[chunk_id, uncompressed_len]
```

Requirements:
- `chunk_id`: 32 bytes
- `uncompressed_len`: positive int and MUST be `<= MAX_DECOMPRESSED_PAYLOAD_BYTES`

Chunking rules:
- extension-envelope file recipes MUST be derived from content-defined chunking under the locked
  chain profile
- virtual root chunk replay MUST use that same locked chunking profile when reconstructing the root
  chunk source

##### 19.3.1.1) Algorithm 1 FastCDC-Style Chunking

When `chunking[0] == 1`, encoders and replay logic MUST apply this FastCDC-style content-defined
chunking algorithm independently to each non-empty file payload. Empty file payloads produce no
chunks.

All integer arithmetic in this subsection is unsigned 64-bit arithmetic modulo `2^64`, unless a
larger range is explicitly required for byte offsets or sizes. `ROT64(value, shift)` means a 64-bit
rotate-left where `shift` is first masked with `63`; therefore `ROT64(value, 64) == value`.

The gear table `G` has 256 unsigned 64-bit entries. It is generated once as follows:

```text
state = 0x9E3779B97F4A7C15
for byte_value in 0..255:
    state = state XOR (state >> 12)
    state = state XOR ((state << 25) mod 2^64)
    state = state XOR (state >> 27)
    state = (state * 0x2545F4914F6CDD1D) mod 2^64
    G[byte_value] = state
```

For a profile `[1, target_size, min_size, max_size]`, derive masks from `target_size`.
`round_half_to_even` means rounding to the nearest integer, with exact half-way values rounded to
the nearest even integer.

```text
target_bits = max(4, round_half_to_even(log2(max(2, target_size))))
primary_bits = min(63, target_bits)
secondary_bits = max(4, target_bits - 2)
primary_mask = (1 << primary_bits) - 1
secondary_mask = (1 << secondary_bits) - 1
```

Each chunk boundary search starts at byte offset `start` with:

```text
fingerprint = 0
window_size = 64
window = 64 zero bytes
window_count = 0
window_pos = 0
```

Because `window_size == 64`, the outgoing byte contribution has rotated through the full 64-bit word
when it leaves the window. The removal term is therefore `G[outgoing]`.

If `remaining_bytes <= min_size`, the final chunk MUST run to end-of-file. Otherwise:

```text
min_end = min(total_len, start + min_size)
target_end = min(total_len, start + target_size)
max_end = min(total_len, start + max_size)

for index in start..(max_end - 1):
    incoming = payload[index]
    if window_count < 64:
        fingerprint = ROT64(fingerprint, 1) XOR G[incoming]
        window[window_pos] = incoming
        window_pos = (window_pos + 1) mod 64
        window_count = window_count + 1
    else:
        outgoing = window[window_pos]
        window[window_pos] = incoming
        window_pos = (window_pos + 1) mod 64
        fingerprint = ROT64(fingerprint, 1) XOR G[outgoing] XOR G[incoming]

    if index + 1 < min_end:
        continue

    mask = primary_mask if index + 1 < target_end else secondary_mask
    if (fingerprint AND mask) == 0:
        cut at index + 1
        stop searching
```

If the scan reaches `max_end` without a mask match, the chunk MUST be cut at `max_end`. The next
boundary search starts at the previous cut offset with a fresh fingerprint and window state.

`chunk_id` is `SHA-256(chunk_bytes)`, where `chunk_bytes` is the exact byte slice between adjacent
chunk offsets. The same locked profile MUST be used for original extension construction and virtual
root chunk replay.

Conformance vectors for profile `[1, 16384, 4096, 65536]`:

```text
input = b""
chunk_end_offsets = []
chunk_sha256 = []

input = bytes(range(256)) * 512
chunk_end_offsets = [65536, 131072]
chunk_sha256 = [
    7daca2095d0438260fa849183dfc67faa459fdf4936e1bc91eec6b281b27e4c2,
    7daca2095d0438260fa849183dfc67faa459fdf4936e1bc91eec6b281b27e4c2,
]

input = b"".join(sha256(i.to_bytes(4, "big")).digest() for i in range(4096))
chunk_end_offsets = [18096, 26931, 43917, 62046, 73496, 93396, 110690, 125496, 130017, 131072]
chunk_sha256 = [
    2ee1e2166281185f001965a7c45631c880b8732f3f48a3f23d61805da105dda8,
    eb1e03f0bac68f0171871be76601ab5e8ff1cd0b6ebe65fec952d4008d49d8ba,
    715518ae12c7f500032a27dd79d7605f65e3b407ee2fe4b069f6deb8234ad476,
    878633ff4a700041ebd6d4d852aed0215f6710cf6991d4f321a3b2fd2b2be830,
    782c360b17d0e7cf76562843a8a199572c79e424f914ec72a79b35c2a5953480,
    da2fa8816f90d81e80df05a7728bc46329dc0d77ea994cf91a21d4a4ae7d5fb1,
    67b130801247f8d07cd21510e6bc3f37bb5b6a382b68ce9d622e464585647b38,
    e8b033381f576d7d299a60c4fde4a718d3ebe2d15f6a914d2e5d5188108cc701,
    eb32376d8f8546f442fac429456036034c22a9cee10c70fd39c3f575abe5696e,
    dfd9fa02180e25f17871e98fd975ba8145952dc3e48f01b28ba4f1f8bee17df5,
]

input = ("alpha beta gamma delta\n" * 4096).encode("utf-8")
chunk_end_offsets = [65536, 94208]
chunk_sha256 = [
    bfa07175ee95b43642ae3fbcad382d7ecf5dd7fad2d496933ad68e7f14f803af,
    d4ffdf00862a1b920325b2fabc25e8621cbb7ce8171803702285b078fd0259c2,
]
```

#### 19.3.2) Chunk Record

Each chunk record MUST be:

```text
[chunk_id, codec, raw_len, data]
```

Requirements:
- `chunk_id`: 32 bytes and MUST equal `SHA-256(decoded_chunk_bytes)`
- `codec`: int
  - `0` = raw
  - `1` = gzip
- `raw_len`: positive int and MUST be `<= MAX_DECOMPRESSED_PAYLOAD_BYTES`
- `data`: non-empty bytes

Inline chunk bounds:
- decoders MUST reject an extension when the sum of inline chunk `raw_len` values exceeds
  `MAX_DECOMPRESSED_PAYLOAD_BYTES`
- this aggregate bound MUST be checked before decompressing inline chunk data

Raw chunk rules:
- when `codec == 0`, `len(data)` MUST equal `raw_len`

Gzip chunk rules:
- when `codec == 1`, decompression MUST produce exactly `raw_len` bytes
- decoders MUST reject gzip chunk data with trailing bytes, incomplete streams, or output that
  exceeds `raw_len`

Write-path rules:
- encoders MAY emit either raw or gzip chunk records per chunk
- encoders SHOULD emit gzip only when it is smaller than raw for that chunk and still satisfies the
  extension-envelope validation rules

#### 19.3.3) Ordering and Uniqueness

Requirements:
- `files` MUST be ordered by normalized `path` in ascending Unicode code point order
- duplicate `path` values are invalid
- `chunks` MUST be ordered by raw `chunk_id` bytes in ascending order
- duplicate `chunk_id` values are invalid
- `len(files)` MUST be `<= MAX_MANIFEST_FILES` (Section 17)

### 19.4) Extension Chain Rules

A valid extension chain is a standalone root Version 1 backup plus zero or more authenticated
extension envelopes selected by content-import recovery and ordered by decrypted chain metadata
(Section 20).

`chain_id` is deterministic chain metadata derived from the authenticated root backup identity:

```text
chain_id = BLAKE2b-256(CHAIN_ID_PERSONALIZATION || root_doc_hash)
```

`chain_id` is not an extension header field, is not stored in extension artifacts, and does not
replace per-link `parent_doc_hash` or `root_doc_hash` validation. Tooling MAY expose `chain_id` as
informational derived metadata, but validators MUST derive it from authenticated root state and MUST
NOT trust a caller-supplied or serialized `chain_id` value as evidence of chain membership.

Requirements:
- every extension ciphertext in one chain MUST decrypt with the same passphrase as the root backup
- an appendable root MUST be unsealed and carry its signing seed in the encrypted Version 1
  manifest; possession of the root carriers plus material sufficient to unlock that manifest is
  therefore sufficient to create an authenticated extension
- chain validation MUST start from the authenticated root `doc_hash`
- after Section 8 deduplication, each extension MUST carry exactly one distinct AUTH payload bound
  to its ciphertext `doc_hash`
- in authenticated mode, each extension AUTH payload MUST verify successfully and its `pub` MUST
  match `root_sign_pub` from Section 7.2
- extension `index` values MUST be sequential from `1`
- for each link:
  - `header.index` MUST equal the expected next extension index
  - `header.root_doc_hash` MUST equal the root backup `doc_hash`
  - `header.parent_doc_hash` MUST equal the exact previous validated document hash
- the first validated extension locks the chain chunking profile
- every later extension in the same chain MUST carry the exact same chunking profile
- signing authority for extension-local validation is derived from the embedded signing seed of the
  unsealed root backup; it is not embedded in the extension header

Chain resource profile:
- one recovery or append session MUST admit at most `MAX_RECOVERY_DOCUMENTS` complete MAIN
  documents, including the root
- the sum of their ciphertext lengths MUST be `<= MAX_RECOVERY_CIPHERTEXT_BYTES`
- the sum of inline chunk `raw_len` values across all admitted extensions MUST be
  `<= MAX_RECOVERY_DECODED_CHUNK_BYTES`
- implementations MUST enforce document count and aggregate ciphertext before decryption, and MUST
  enforce the remaining decoded-chunk budget from declared canonical bodies before decompressing an
  extension's inline chunks
- encoders MUST NOT emit an extension that would cross a chain limit

Append implementations MUST preserve the rule that a chunk record is introduced at most once over
the complete chain. They MAY bound working memory by retaining raw chunk bytes only for the latest
logical state and tracking older introduced chunks by `chunk_id`. When selected input contains bytes
whose `SHA-256` matches such an older `chunk_id`, the writer MUST emit a reference to that
historical chunk rather than reintroducing it inline.

Operational rescue modes that tolerate unsigned or invalid extension AUTH are outside the
authenticated format described in this section. Implementations MUST NOT describe replay of an
unsigned or invalidly signed extension as conforming to this format.

### 19.5) Extension Replay

Replay produces the latest logical file set by starting from the root Version 1 manifest/payload
and then applying validated extensions in order.

Replay rules:
- paths omitted from an extension inherit their previous logical state unchanged
- paths present in an extension replace the previous logical state for that path
- extensions cannot represent deletes or tombstones; a path that existed in the root or an earlier
  extension remains recoverable unless a later extension replaces it with new file content
- an extension is therefore an add-or-replace operation, not filesystem synchronization; encoding a
  renamed path adds the new path without removing the old path
- each chunk reference MUST resolve to either:
  - a newly introduced chunk in the current or earlier validated extension, or
  - a chain-global virtual root chunk, keyed by the `SHA-256` of each re-chunked root chunk byte
    sequence under the locked chain chunking profile
- a chunk record carried by the current extension's `chunks` array MUST be newly introduced at
  that extension index; replay MUST reject it if the same `chunk_id` is already available from the
  chain-global virtual root chunk source or an earlier validated extension
- replacing a root path changes latest logical state for that path, but does not remove the
  corresponding root payload bytes from the chain-global virtual root chunk source
- replay MUST reject unresolved `chunk_id` references
- replay MUST reject any reconstructed file whose size or SHA-256 does not match its recipe
- total reconstructed logical files MUST remain `<= MAX_MANIFEST_FILES`
- total reconstructed logical bytes MUST remain `<= MAX_DECOMPRESSED_PAYLOAD_BYTES`
- when replay emits a synthetic Version 1 manifest for reconstructed extension state, it
  MUST identify file provenance with `input_origin == "directory"` and
  `input_roots == ["reconstructed-state"]`; it MUST NOT inherit root input provenance or the latest
  extension header scope
- synthetic replay manifests MUST preserve the root sealed/unsealed state and, for an unsealed
  root, the exact root signing seed

## 20) Content-Addressed Extension Selection

Extension recovery is content-addressed. Directory names, filenames, file order, and carrier labels
are not part of extension identity and MUST NOT be required to recover an extension chain.

Selection rules:

- implementations MUST accept scanned, pasted, or otherwise imported carriers without requiring a
  particular directory layout or filename convention;
- MAIN frames MUST be grouped by frame `doc_id`, and each group MUST independently reassemble to
  one ciphertext;
- the authoritative `doc_id` and `doc_hash` MUST be derived from recovered ciphertext;
- AUTH frames MUST be matched by frame `doc_id` and verified against the derived ciphertext
  `doc_hash`;
- decrypted envelope version 1 documents are root-backup candidates;
- decrypted envelope version 2 documents are extension candidates;
- a recovery session MUST select exactly one root backup or reject the input as ambiguous;
- extension candidates MUST authenticate under `root_sign_pub` established in Section 7.2 before
  replay;
- extension order MUST come from the decrypted header `index` and ancestry fields, not from
  filesystem position;
- distinct authenticated extensions at the same `index` MUST be rejected as an ambiguous fork.

Recovery MAY use any complete authenticated machine-readable MAIN carrier for a document. Multiple
carrier copies provide redundancy and do not create additional document identities. Publication
layout and redundancy audits are defined separately in the
[extension operations and publication profile](extension_publication_profile.md) and MUST NOT change
content-addressed identity.

Content import authenticates only the carriers supplied to the session. Without a separate trusted
freshness source, an implementation MUST NOT claim that no later extension exists. Independent
appends from one authenticated head can form distinct valid forks. Either fork MAY validate alone;
supplying conflicting forks for one selection MUST fail as ambiguous.

In this format, `latest` means the latest valid authenticated state among the supplied carriers.
No global ledger or online head registry is consulted. Under the v1.2 operations profile, browser
recovery MUST NOT silently use that target: it requires a chain-bound-kit head pin, a manually
entered expected head, or an explicit acknowledgement that freshness beyond the supplied pages is
unknown.

The authoritative extension identity consists of recovered ciphertext, its verified AUTH payload,
and decrypted extension-header metadata.
