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
  "created": created_at,    // float or int (unix epoch seconds)
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
- `created`: int or float
- `sealed`: bool
- `seed`:
  - if `sealed` is true, `seed` MUST be null
  - if `sealed` is false, `seed` MUST be 32 bytes
- `files`: list of entries, MUST contain at least one file entry

File list requirements:
- Encoders MUST reject empty `files` lists at creation time.
- Decoders MUST reject manifests/envelopes with empty `files` lists.

File entry requirements (map keys):
- `path`: non-empty string
- `size`: non-negative int
- `hash`: 32 raw bytes (SHA-256 of file contents, not hex)
- `mtime`: int or null

CBOR encoding requirements:
- Manifests MUST use canonical CBOR encoding (RFC 8949) for deterministic output.
- Indefinite-length CBOR items MUST NOT be used.

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

Frame DATA semantics (Version 1):
- For `FRAME_TYPE=MAIN_DOCUMENT`, reassembly of all frames in the group yields the complete age
  ciphertext (Section 13).
- For `FRAME_TYPE=AUTH`, DATA MUST be the canonical CBOR encoding of the Auth payload (Section 8).
- For `FRAME_TYPE=KEY_DOCUMENT`, DATA MUST be the canonical CBOR encoding of the Shard payload
  (Section 9).

CRC:
- CRC32 is computed over all bytes before the CRC field.
- CRC32 algorithm is CRC-32/ISO-HDLC (PKZIP / IEEE 802.3): polynomial 0x04C11DB7
  (reflected 0xEDB88320), init 0xFFFFFFFF, refin=true, refout=true, xorout=0xFFFFFFFF.

INDEX/TOTAL semantics:
- INDEX is 0-based and MUST satisfy 0 ≤ INDEX < TOTAL.
- TOTAL MUST be ≥ 1.

Frame reassembly:
- Frames MAY be provided out of order; decoders MUST accept out-of-order frames.
- Frames MUST be grouped by DOC_ID and FRAME_TYPE; frames from different documents MUST NOT be
  combined in the same reassembly.
- Within a reassembly group, all frames MUST have the same VERSION and TOTAL.
- Reassembly concatenates DATA in ascending INDEX order (INDEX 0, 1, 2, ... TOTAL-1).
- Decoders MUST reject incomplete frame sets (missing any INDEX).
- Duplicate frames (same DOC_ID + FRAME_TYPE + INDEX):
  - If TOTAL and DATA are identical, decoders SHOULD ignore the duplicate.
  - If TOTAL or DATA differs, decoders MUST reject as conflicting duplicates.

Single-frame payloads (Version 1):
- AUTH and KEY_DOCUMENT payloads MUST be encoded as a single frame (frame index=0, frame total=1).

## 7) Document Identifiers

Definitions:
- `doc_hash` = BLAKE2b-256(ciphertext) (unkeyed BLAKE2b with 32-byte digest)
- `doc_id` = first 8 bytes of `doc_hash`

`doc_id` is stored in every frame.
`doc_hash` is signed and embedded in the auth/shard payloads.

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

CBOR encoding requirements:
- Auth payloads MUST use canonical CBOR encoding (RFC 8949) for deterministic output.
- Indefinite-length CBOR items MUST NOT be used.

Signature domain:
- Let `signed_auth_payload` be the auth payload CBOR map with the `sig` field omitted.
- Message is `AUTH_DOMAIN + canonical_cbor(signed_auth_payload)`
- AUTH_DOMAIN is defined in Section 2.1.

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

Signature domain:
- Let `signed_shard_payload` be the shard payload CBOR map with the `sig` field omitted.
- Message is `SHARD_DOMAIN + canonical_cbor(signed_shard_payload)`
- SHARD_DOMAIN is defined in Section 2.1.

Each shard MUST be encoded as a single frame (frame index=0, frame total=1).

## 10) QR Payload Encoding

QR payload text MUST be base64 without padding.

Encoding:
- Base64 encode the raw frame bytes.
- Strip trailing "=" padding characters.

Decoding:
- Restore padding to a multiple of 4.
- Base64 decode with validation.

Decoders MUST ignore whitespace in payloads.

## 11) Fallback Text Encoding

Fallback text MUST encode the raw frame bytes with z-base-32.

Encoding:
- Alphabet: `ybndrfg8ejkmcpqxot1uwisza345h769`
- Encoders MAY insert arbitrary whitespace and dashes (`-`) for readability.

Decoding:
- Remove whitespace and dashes (`-`), decode z-base-32 to raw frame bytes.

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

### 14.4) Reference

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
- At least t shares with distinct indices

Process:
- Lagrange interpolation over GF(2^128)
- Applied per 16-byte block
- Result truncated to original `length`

Output:
- Original secret bytes

### 15.5) Constraints

- Maximum index: 255
- Minimum threshold: 1
- Maximum threshold: n
- Maximum shares: 255

Validation:
- 1 ≤ threshold ≤ share_count ≤ 255
- 1 ≤ share_index ≤ share_count
- All indices in a reconstruction set MUST be distinct

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

### 16.2) Normalization Function

Let `normalize_path(path)` return Unicode NFC normalization of `path`.

### 16.3) Reference

Unicode Normalization Forms: https://unicode.org/reports/tr15/
