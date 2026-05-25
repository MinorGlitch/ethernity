# Ethernity Core Format Specification

This document specifies the stable on-paper and on-disk core formats for Ethernity: the envelope,
manifest, frame encoding, QR payloads, and fallback text.

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT", "SHOULD", "SHOULD NOT",
"RECOMMENDED", "MAY", and "OPTIONAL" in this document are to be interpreted as described in RFC
2119.

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
- Extension envelope replay, content-import recovery, and compaction

Non-goals:
- CLI UX and UI
- Rendering layout or templates
- Rationale and operational notes (see `docs/format_notes.md`)

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
- `input_roots`: list of non-empty UTF-8 strings, each a leaf label (no `/` or `\`)
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
- Decoders MUST ignore unknown top-level manifest keys.
- Unknown top-level manifest keys are extension data only and MUST NOT affect signature verification
  decisions, key reconstruction eligibility, or authenticated/rescue trust labeling.
- Encoders SHOULD NOT emit unknown top-level manifest keys for `MANIFEST_VERSION = 1`.
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

CBOR encoding requirements:
- Manifests MUST use canonical CBOR encoding (RFC 8949) for deterministic output.
- Indefinite-length CBOR items MUST NOT be used.
- Decoders MUST reject manifests that are not canonical CBOR (including any indefinite-length
  item).
- Decoders MUST validate canonical CBOR for MANIFEST_BYTES at the envelope decode boundary before
  applying manifest semantic validation.

Ordering:
- Encoders MUST compute each file entry ordering key as
  `normalize_path(reconstructed_path(entry))` (Section 16).
- Encoders MUST sort file entries by ordering key in ascending Unicode code point order before
  manifest creation.
- Payload concatenation MUST follow this same ordering key order.

### 3.1) Sealing

Sealing semantics are normative in Section 3 (`sealed`/`seed` cross-field rules); this subsection
is informative only.

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
- For gzip mode, decoders MUST reject payloads where decompression emits more than
  `payload_raw_len` bytes.
- For gzip mode, decoders MUST reject payloads where final decompressed length is not exactly
  `payload_raw_len`.
- For gzip mode, decoders MUST require a complete gzip stream (end-of-stream reached).
- For gzip mode, decoders MUST reject payloads with trailing bytes after the gzip stream.
- For gzip mode, decoders MUST reject manifests with `payload_raw_len` greater than
  `MAX_DECOMPRESSED_PAYLOAD_BYTES`.
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
- Decoders MUST ignore unknown auth payload keys.
- Unknown auth payload keys are extension data only and MUST NOT affect signature verification
  decisions, key reconstruction eligibility, or authenticated/rescue trust labeling.
- Encoders SHOULD NOT emit unknown auth payload keys for `AUTH_VERSION = 1`.

CBOR encoding requirements:
- Auth payloads MUST use canonical CBOR encoding (RFC 8949) for deterministic output.
- Indefinite-length CBOR items MUST NOT be used.
- Decoders MUST reject auth payloads that are not canonical CBOR (including any indefinite-length
  item).
- Decoders MUST validate canonical CBOR for AUTH payload DATA at frame decode boundary before
  signature verification or semantic validation.

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
- Decoders MUST ignore unknown shard payload keys.
- Unknown shard payload keys are extension data only and MUST NOT affect signature verification
  decisions, key reconstruction eligibility, or authenticated/rescue trust labeling.
- Encoders SHOULD NOT emit unknown shard payload keys.

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

CBOR encoding requirements:
- Shard payloads MUST use canonical CBOR encoding (RFC 8949) for deterministic output.
- Indefinite-length CBOR items MUST NOT be used.
- Decoders MUST reject shard payloads that are not canonical CBOR (including any indefinite-length
  item).
- Decoders MUST validate canonical CBOR for KEY_DOCUMENT payload DATA at frame decode boundary
  before signature verification or semantic validation.

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
  2. For each line, remove all Unicode whitespace code points and ASCII dashes (`-`).
  3. If the resulting string is empty, discard it.
  4. The remaining string MUST consist only of z-base-32 alphabet characters
     (`ybndrfg8ejkmcpqxot1uwisza345h769`) when compared case-insensitively.
  5. Normalize the remaining string to lowercase ASCII and append it to the filtered-line list.
- `MAX_FALLBACK_LINES` counts the number of filtered lines after Step 5.
- `MAX_FALLBACK_NORMALIZED_CHARS` counts the sum of lengths of all filtered lines after Step 5.
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

### 12.1) Stable v1 Profile Baseline Contract

This document defines the stable v1 profile baseline.

Stable v1 profile requirements:
- Envelope/frame magic constants, frame types, and version constants remain unchanged from Version 1.
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

### 15.2) Share Generation

Input:
- Secret: arbitrary-length byte string
- Threshold (t): minimum shares required for reconstruction
- Total (n): total shares to generate

Process:
- Secret is chunked into 16-byte blocks
- Shamir applied independently to each block
- For each block polynomial, coefficients (except the secret constant term) MUST be generated with
  a cryptographically secure random number generator and sampled uniformly over GF(2^128).
- Encoders MUST NOT derive Shamir coefficients from predictable or deterministic non-cryptographic
  sources (for example timestamps, counters, or process IDs).
- Padding: if the final block is shorter than 16 bytes, it is right-padded with zero bytes (0x00)
  to exactly 16 bytes.
- The original unpadded secret length is stored in the shard payload field `length`.

Output:
- n shares, each containing index and share data
- Share indices: 1 to n (1-indexed)

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

### 15.6) Reference

- Shamir, Adi. "How to share a secret." Communications of the ACM 22.11 (1979): 612-613.

## 16) Path Normalization

### 16.1) Unicode Normalization

All file paths MUST be normalized to Unicode NFC (Canonical Decomposition, followed by Canonical
Composition) form.

Requirements:
- Paths MUST be normalized to NFC before storage in manifest
- Paths MUST be normalized to NFC before any comparison operation
- Paths that are not valid UTF-8 MUST be rejected
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

This section defines mandatory Version 1 resource bounds.

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

## 18) Normative Conformance Appendix

This appendix is normative. Conforming stable v1 implementations MUST satisfy all requirements in
this section.

### 18.1) Required Decoder Validation Order

Decoders MUST apply validation in this order:
1. Parse framing/envelope boundaries and reject non-canonical uvarints at each decode boundary.
2. Enforce resource bounds (Section 17) before unbounded allocation or reconstruction.
3. Decode CBOR payloads and reject non-canonical CBOR at manifest/auth/shard boundaries.
4. Apply structural validation for manifest/auth/shard fields and cross-field constraints.
5. Apply binding and consistency checks (`doc_id`/`doc_hash`, shard set consistency, payload hash
   checks).
6. Apply signature-policy checks according to authenticated or rescue mode.
7. Emit trust labeling that reflects the applied mode and verification outcome.

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

## 19) Extension Chain Format (Extension Envelope)

The extension envelope is an authenticated append-only document that lives beside a standalone root
backup. The root backup remains a Version 1 envelope. Each extension is a separately encrypted MAIN
document whose ciphertext has its own `doc_hash` and `doc_id` under Section 7. On the wire, the
extension envelope uses outer envelope `VERSION = 2`.

Extension authentication is carried beside the ciphertext, not inside the encrypted extension
header/body. Extension recovery MUST verify exactly one AUTH payload bound to the extension
ciphertext `doc_hash` and signed by the selected root-derived signing authority. Published export
layouts carry this AUTH payload with the extension MAIN transport and may also display it in
human-readable fallback text; there is no separate extension AUTH artifact filename in the core
format.

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
- `HEADER_BYTES` and `BODY_BYTES` MUST each be canonical CBOR and MUST NOT use indefinite-length
  items.
- Decoders MUST reject non-canonical uvarints, non-canonical CBOR, truncated header/body sections,
  or extra bytes after `BODY_BYTES`.
- `HEADER_BYTES` and `BODY_BYTES` MUST each be `<= MAX_MANIFEST_CBOR_BYTES` (Section 17).

As with Version 1, encoders MUST encrypt the complete extension envelope as a single age message
and then frame the resulting ciphertext according to Section 6.

Published machine-readable extension carriers MUST also provide one AUTH frame for that ciphertext:
- the AUTH payload MUST bind to the extension ciphertext `doc_hash`
- the AUTH payload MUST be encoded as a single-frame AUTH payload
- the AUTH signature MUST be produced by the root-derived signing authority
- AUTH carrier transport reuses the existing machine-readable MAIN carrier set; no extra extension
  AUTH filename is introduced

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
- `index`: positive int (`>= 1`)
- `parent_doc_hash`: 32 bytes
- `root_doc_hash`: 32 bytes
- `created_at`: int
- `chunking`: list `[algorithm_id, target_size, min_size, max_size]`
  - all values MUST be positive ints
  - `target_size`, `min_size`, and `max_size` MUST each be
    `<= MAX_DECOMPRESSED_PAYLOAD_BYTES`
  - `min_size <= target_size <= max_size`
  - `algorithm_id == 1` identifies the extension-envelope FastCDC-style content-defined chunking
    profile
  - encoders and replay logic MUST honor the full profile; they MUST NOT treat `target_size` as a
    fixed-size slicing width
- `input_origin`: `"file"`, `"directory"`, or `"mixed"`
- `input_roots`:
  - each root MUST be a non-empty UTF-8 leaf label
  - roots are NFC-normalized but otherwise preserved exactly; decoders MUST NOT trim leading or
    trailing whitespace
  - roots MUST NOT contain `/` or `\\`
  - MUST be empty when `input_origin == "file"`
  - MUST be non-empty when `input_origin` is `"directory"` or `"mixed"`

Unknown header keys MUST be rejected.
Header keys `3`, `6`, `8`, and `9` are not part of the Version 2 extension schema and MUST be
rejected.

### 19.3) Extension Body

The extension body MUST be a CBOR map with exactly these integer keys:

```text
1 -> files
2 -> chunks
```

`files` MUST be a non-empty array of file recipes. `chunks` MUST be an array of newly introduced
chunk records and MAY be empty. Each chunk record in `chunks` MUST be referenced by at least one file
recipe in the same extension body.

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
- `uncompressed_len`: positive int

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

A valid extension chain is a standalone root Version 1 backup plus zero or more extension
envelopes discovered from disk (Section 20).

`chain_id` is deterministic chain metadata derived from the authenticated root backup identity:

```text
chain_id = BLAKE2b-256(CHAIN_ID_PERSONALIZATION || root_doc_hash)
```

`chain_id` is not an extension header field and does not replace per-link `parent_doc_hash` or
`root_doc_hash` validation.

Requirements:
- every extension ciphertext in one chain MUST decrypt with the same passphrase as the root backup
- chain validation MUST start from the authenticated root `doc_hash`
- each extension MUST carry exactly one AUTH payload bound to its ciphertext `doc_hash`
- in authenticated mode, each extension AUTH payload MUST verify successfully and its `sign_pub`
  MUST match the root-derived signing authority
- extension `index` values MUST be sequential from `1`
- for each link:
  - `header.index` MUST equal the expected next extension index
  - `header.root_doc_hash` MUST equal the root backup `doc_hash`
  - `header.parent_doc_hash` MUST equal the exact previous validated document hash
- the first validated extension locks the chain chunking profile
- every later extension in the same chain MUST carry the exact same chunking profile
- signing authority for extension-local validation is derived from the embedded signing seed of the
  unsealed root backup; it is not embedded in the extension header

Operational rescue modes that tolerate unsigned or invalid extension AUTH are outside the
normative authenticated profile described in this section.
Implementations MUST NOT replay extensions in rescue mode unless they define a separate
non-authenticated extension profile. The CLI/API profile defined for this release does not expose
rescue-mode extension replay.

### 19.5) Extension Replay

Replay produces the latest logical file set by starting from the root Version 1 manifest/payload
and then applying validated extensions in order.

Replay rules:
- paths omitted from an extension inherit their previous logical state unchanged
- paths present in an extension replace the previous logical state for that path
- extensions cannot represent deletes or tombstones; a path that existed in the root or an earlier
  extension remains recoverable unless a later extension replaces it with new file content
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
- when replay emits a synthetic Version 1 manifest for recovered or compacted extension state, it
  MUST identify file provenance with `input_origin == "directory"` and
  `input_roots == ["reconstructed-state"]`; it MUST NOT inherit root input provenance or the latest
  extension header scope
- synthetic replay manifests MUST preserve root chain security fields required for recovery and
  compaction, including the root sealed/unsealed state and the unsealed root signing seed

## 20) Content-Import Extension Recovery

Extension recovery is content-addressed. Directory names, filenames, file order, and carrier labels
are not part of extension identity and MUST NOT be required to recover an extension chain.

Import rules:
- implementations MUST accept a set of scanned or pasted recovery carriers without requiring a
  particular directory layout or filename convention
- recursive directory scans of backup-export trees MUST exclude unpublished extension transaction
  workspaces named `extensions/.staging-*`; carriers in those workspaces are not published by the
  directory root
- backup-export tree scans MUST treat extension-like non-canonical top-level entries under
  `extensions/` as layout errors, including stale extension directory names such as `extension-01`
  and extension artifact files placed directly under `extensions/`; clearly unrelated clutter MAY be
  ignored
- when a caller explicitly selects the root backup head, recursive backup-export scans MUST NOT
  require canonical published extension carrier files to be readable; implementations MAY ignore
  published extension carrier contents after enforcing the `extensions/` top-level layout rules
- MAIN frames MUST be grouped by frame `doc_id`; each group MUST independently reassemble to one
  ciphertext
- the authoritative `doc_id` and `doc_hash` MUST be derived from recovered ciphertext
- AUTH frames MUST be matched by frame `doc_id` and verified against the derived ciphertext
  `doc_hash`
- decrypted Version 1 envelopes are root-backup candidates
- decrypted Version 2 envelopes are extension candidates
- a recovery session MUST select exactly one root backup, or fail with an ambiguity error
- extension candidates MUST be authenticated by the root-derived signing authority before replay
- extension ordering MUST come from decrypted extension-header `index` and ancestry fields, not from
  filesystem position
- duplicate authenticated extensions for the same `index` with different `doc_hash` values MUST be
  rejected as ambiguous
- content import authenticates only the recovery carriers supplied to the recovery session; without
  a separate signed freshness source, implementations MUST NOT claim to prove that no later
  extension exists

Recovery MAY succeed from any complete, authenticated machine-readable MAIN carrier for a document.
Multiple carrier copies are redundancy, not identity. Implementations MAY provide separate audit
tooling for checking whether an exported digital folder contains all expected redundant artifacts,
but such audit rules are outside the recovery format.

Recovery-valid and append-valid are distinct states. A recovery implementation MAY restore content
from a complete authenticated machine-readable carrier set even when a published export tree is
missing redundant human-readable artifacts. An implementation that appends a new published
extension, however, MUST require the existing published chain head to satisfy the canonical export
layout before publishing the next extension. For this release profile, a published extension
directory is append-valid only when the required `qr_document-*` and `recovery_document-*` MAIN
artifacts are present and pass publish/discovery validation. If shard artifacts are present in the
published extension directory, each shard document type MUST form a complete set with one declared
`share_count` and share indexes `1..share_count`; passphrase shards and signing-key shards are
validated as independent sets.

For this release profile, `qr_document-*` artifacts are the only machine-readable
payload-bearing MAIN carriers in a canonical published extension directory. This filename role is an
export-layout rule, not a recovery-input naming requirement: scan/import MAY accept any user-supplied
PDF or image filename when the file content contains complete, authenticated machine-readable QR
payloads. Extension `recovery_document-*` artifacts are human-readable fallback documents for manual
transcription when QR scanning is unavailable or damaged. Manually typed or transcribed fallback text
MAY be accepted through explicit text inputs, but implementations MUST NOT extract or parse fallback
text from PDF or image files as a content-import or chain-replay carrier. Publish implementations
MUST validate every machine-readable payload-bearing carrier before promotion. They MAY also perform
PDF integrity and visible fallback-text checks on recovery documents, but MUST NOT derive recovery
semantics by scraping human-display text from the PDF.

The authoritative extension identity comes from recovered ciphertext, AUTH, and decrypted
extension-header metadata.

## 21) Selected Recovery, Minting, and Compaction

Selected recovery rules:
- default recovery from content import MUST fail closed when the latest supplied authenticated
  extension head cannot be reconstructed, authenticated, or replayed
- when all imported extensions for the selected root are valid, default recovery MUST replay through
  the latest supplied authenticated extension
- recovery MAY select an earlier target by extension `index`
- recovery MAY select an earlier target by authenticated extension `doc_hash`
- selecting index `0` means root-only recovery without replaying any extension

Shard minting rules:
- minting shard documents for an imported extension head MUST authenticate ancestry and fully replay
  the selected root-plus-extension chain before using that head's `doc_id`, `doc_hash`, or AUTH as
  the shard binding target
- minting MUST fail closed when the selected extension head cannot be reconstructed,
  authenticated, or replayed

Compaction rules:
- compaction MUST fully reconstruct the latest supplied validated logical state of a
  root-plus-extension chain
- compaction MUST write that logical state as a fresh standalone Version 1 backup in a separate
  output directory
- compaction MUST preserve the chain passphrase exactly; passphrase rotation is not part of this
  format
- when compaction unlocks the source with passphrase shard carriers validated against the trusted
  root signing authority, the compacted checkpoint MUST emit fresh passphrase shard documents with
  the same threshold and share count; implementations MUST NOT downgrade to a plaintext-passphrase
  checkpoint because source shard documents are stored outside the scanned backup root
- compaction shard policy inheritance MUST be content-first and authenticated: filename prefixes are
  not policy signals, and unsigned or self-authority shard metadata MUST NOT select the compacted
  checkpoint shard policy
- compaction MUST preserve the root sealed/unsealed state
- if the root is unsealed, compaction MUST preserve the root signing seed exactly
- if the root is sealed, compaction MUST NOT emit signing-key shard documents
- compaction MUST NOT mutate or delete the original recovery carriers in place
