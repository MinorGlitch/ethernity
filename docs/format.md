# Ethernity Core Format Specification

This document specifies the stable on-paper and on-disk core formats for Ethernity: the envelope,
manifest, frame encoding, QR payloads, and fallback text.

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT", "SHOULD", "SHOULD NOT",
"RECOMMENDED", "MAY", and "OPTIONAL" in this document are to be interpreted as described in RFC
2119.

Scope:
- Envelope binary container
- Manifest structure and file paths
- Frame encoding (QR and fallback)
- Auth and shard payloads
- Encryption (age)
- Passphrase representation (BIP-39)
- Shamir secret sharing
- Path normalization

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

## 2) Envelope Format

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
PAYLOAD_BYTES (raw)
```

Rules:
- MAGIC MUST equal `0x41 0x59`.
- VERSION MUST equal `1`.
- MANIFEST_LEN and PAYLOAD_LEN MUST match the remaining byte boundaries.
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
  "files": files            // list[file_entry]
}
```

File entry (CBOR map):
```
{
  "path": path,
  "size": size,
  "hash": sha256,
  "mtime": mtime
}
```

Manifest requirements (map keys):
- `version`: int == MANIFEST_VERSION (1)
- `created`: encoders SHOULD emit integer Unix epoch seconds as canonical output
- `created`: decoders MAY accept integer or float values for compatibility with legacy payloads
- `sealed`: bool
- `seed`:
  - if `sealed` is true, `seed` MUST be null
  - if `sealed` is false, `seed` MUST be 32 bytes
- `files`: list of entries, MUST contain at least one file entry
- The canonical CBOR byte length of the manifest MUST be ≤ `MAX_MANIFEST_CBOR_BYTES` (Section 17).
- The number of file entries MUST be ≤ `MAX_MANIFEST_FILES` (Section 17).
- Decoders MUST ignore unknown top-level manifest keys.
- Encoders SHOULD NOT emit unknown top-level manifest keys for `MANIFEST_VERSION = 1`.

File list requirements:
- Encoders MUST reject empty `files` lists at creation time.
- Decoders MUST reject manifests/envelopes with empty `files` lists.

File entry requirements (map keys):
- `path`: non-empty string
- `size`: non-negative int
- `hash`: 32 raw bytes (SHA-256 of file contents, not hex)
- `mtime`: int or null
- Decoders MUST ignore unknown file-entry keys.
- Encoders SHOULD NOT emit unknown file-entry keys for `MANIFEST_VERSION = 1`.

CBOR encoding requirements:
- Manifests MUST use canonical CBOR encoding (RFC 8949) for deterministic output.
- Indefinite-length CBOR items MUST NOT be used.
- Decoders MUST reject manifests that are not canonical CBOR (including any indefinite-length
  item).

Ordering:
- Encoders MUST sort file entries by `path` in ascending Unicode code point order before manifest
  creation.
- Payload concatenation MUST follow this same sorted order.

### 3.1) Sealing

Sealing controls whether the signing seed is present in the encrypted manifest:
- If `sealed` is true, `seed` MUST be null.
- If `sealed` is false, `seed` MUST be 32 bytes.

## 4) File Paths

File paths are stored directly in each file entry as `path`.

Path rules:
- Stored paths MUST use POSIX separators (`/`).
- Paths MUST satisfy the normalization requirements in Section 16.
- Paths that differ only by Unicode normalization are considered identical; duplicates MUST be rejected.
- Paths MUST be relative (no leading `/`).
- Paths MUST NOT contain empty segments (for example `a//b` or a trailing `/`).
- Paths MUST NOT contain `.` or `..` segments.
- Path UTF-8 byte length MUST be ≤ `MAX_PATH_BYTES` (Section 17).

## 5) Payload

Payload bytes MUST be the concatenation of file contents in manifest order.
Decoders MUST verify each entry's SHA-256 against its corresponding payload slice.

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
- Encoders SHOULD NOT emit unknown auth payload keys for `AUTH_VERSION = 1`.

CBOR encoding requirements:
- Auth payloads MUST use canonical CBOR encoding (RFC 8949) for deterministic output.
- Indefinite-length CBOR items MUST NOT be used.
- Decoders MUST reject auth payloads that are not canonical CBOR (including any indefinite-length
  item).

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
- SHARD_VERSION = `1`

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
  "sig": signature
}
```

Requirements:
- `version`: int == SHARD_VERSION (1)
- `type`: "passphrase" or "signing-seed"
- `threshold`/`share_count`/`share_index`/`length`: positive ints
- `share`: bytes
- `hash`: 32 bytes
- `pub`: 32 bytes
- `sig`: 64 bytes
- Decoders MUST ignore unknown shard payload keys.
- Encoders SHOULD NOT emit unknown shard payload keys for `SHARD_VERSION = 1`.

Validation rules:
- `threshold`: MUST satisfy 1 ≤ threshold ≤ share_count
- `share_count`: MUST satisfy share_count ≥ 1
- `share_index`: MUST satisfy 1 ≤ share_index ≤ share_count
- `share`/`length` consistency:
  - `share` length MUST be a multiple of 16 bytes.
  - `length` MUST satisfy 1 ≤ length ≤ len(share).
  - len(share) MUST equal `ceil(length/16) * 16`.

Decoders MUST reject shard payloads that violate these bounds.

CBOR encoding requirements:
- Shard payloads MUST use canonical CBOR encoding (RFC 8949) for deterministic output.
- Indefinite-length CBOR items MUST NOT be used.
- Decoders MUST reject shard payloads that are not canonical CBOR (including any indefinite-length
  item).

Signature domain:
- Let `signed_shard_payload` be a CBOR map containing exactly:
  `version`, `type`, `threshold`, `share_count`, `share_index`, `length`, `share`, `hash`, and
  `pub`.
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
- Duplicate `share_index` handling:
  - If the duplicated `share` bytes are identical, decoders SHOULD ignore the duplicate.
  - If the duplicated `share` bytes differ, decoders MUST reject.
- Set-level consistency requirements for `hash`, `pub`, `type`, `threshold`, and `share_count`
  apply to the deduplicated reconstruction set after duplicate `share_index` resolution.
- Decoders MAY perform stricter validation earlier (for example, rejecting duplicate entries that
  disagree on consistency fields even when `share` bytes match).

A recovery set MAY contain multiple `KEY_DOCUMENT` frames for the same DOC_ID.
Each shard payload MUST be encoded as a single frame (frame index=0, frame total=1).

## 10) QR Payload Encoding

QR payload text MUST be base64 without padding.
Version 1 defines no alternative QR payload encodings.

Encoding:
- Base64 encode the raw frame bytes.
- Strip trailing "=" padding characters.

Decoding:
- After whitespace removal, payload text MUST NOT contain "=" characters.
- Restore padding to a multiple of 4.
- Base64 decode with validation.

Decoders MUST ignore whitespace in payloads.
After whitespace removal, payload text length MUST be ≤ `MAX_QR_PAYLOAD_CHARS` (Section 17).
Encoders and decoders MUST NOT negotiate or auto-detect alternate QR payload encodings in Version 1.

## 11) Fallback Text Encoding

Fallback text MUST encode the raw frame bytes with z-base-32.

Encoding:
- Alphabet: `ybndrfg8ejkmcpqxot1uwisza345h769`
- Encoders MAY insert arbitrary whitespace and dashes (`-`) for readability.

Decoding:
- Remove whitespace and dashes (`-`), decode z-base-32 to raw frame bytes.
- Decoders MUST treat z-base-32 letters case-insensitively.
- For each fallback section, decoders MUST reject more than `MAX_FALLBACK_LINES` filtered lines
  (Section 17).
- For each fallback section, decoders MUST reject more than
  `MAX_FALLBACK_NORMALIZED_CHARS` normalized z-base-32 characters (Section 17).
- Recovery text sources (files/stdin) MUST be rejected if byte length exceeds
  `MAX_RECOVERY_TEXT_BYTES` (Section 17).

## 12) Version Markers

Version markers:
- Envelope: MAGIC + VERSION
- Manifest: MANIFEST_VERSION
- Frames: MAGIC + VERSION
- Auth: AUTH_VERSION
- Shards: SHARD_VERSION

Current version values (Version 1):
- Envelope VERSION = `1`
- Frame VERSION = `1`
- MANIFEST_VERSION = `1`
- AUTH_VERSION = `1`
- SHARD_VERSION = `1`

### 12.1) v1.1 Clarification and Compatibility Notes

This specification revision is a v1.1 clarification pass only. It does not change the v1 wire
format, binary framing, or payload layouts.

Compatibility and extensibility guidance:
- Manifest/auth/shard payloads are CBOR maps. Decoders ignore unknown keys for forward
  compatibility; encoders should avoid emitting undefined keys in v1 payloads.
- Frame types are closed for v1. Decoders reject frame-type values outside the defined set in
  Section 6.
- QR payload encoding remains fixed to base64 without padding in v1. Runtime/profile negotiation of
  alternate encodings is not permitted.
- Parsing remains fail-closed: malformed canonical encodings or invalid structural/binding content
  must be rejected.

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

### 14.4) Non-BIP-39 Interoperability Guidance

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

Decoders MUST reject shard payloads where `share` and `length` are inconsistent.

### 15.4) Reconstruction

Input:
- At least t shares after applying duplicate handling rules from Section 9

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
- Paths MUST NOT contain empty segments
- Paths MUST NOT contain `.` or `..` segments

### 16.2) Normalization Function

Let `normalize_path(path)` return Unicode NFC normalization of `path`.

### 16.3) Reference

Unicode Normalization Forms: https://unicode.org/reports/tr15/

## 17) Resource Bounds

This section defines mandatory Version 1 resource bounds.

Encoders MUST NOT emit artifacts that exceed these bounds.
Decoders MUST reject inputs that exceed these bounds.

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
