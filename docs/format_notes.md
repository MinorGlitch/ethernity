# Ethernity Format Notes (Non-normative)

This document contains rationale and operational guidance that is intentionally excluded from the
core wire/on-disk format specification (`docs/format.md`).

## Sealing: Rationale and Use Cases

Sealing controls whether the signing seed is recoverable from the encrypted manifest.

Typical guidance:
- Prefer unsealed envelopes when you want maximum recoverability (the encrypted envelope can be used
  to regenerate signed recovery materials after decryption).
- Prefer sealed envelopes when you want the printed recovery/shard documents to be the final source
  of signing authority (the signing seed is not stored anywhere inside the encrypted envelope).

Sealing is effectively irreversible for a given ciphertext identity: changing sealing state requires
creating a new envelope, which produces a different ciphertext and therefore different `doc_hash` /
`doc_id`.

## Security Model Notes

The Ethernity recovery flow combines:
- Encryption (age) for confidentiality + integrity of the envelope.
- Signatures (Ed25519) to authenticate auxiliary recovery artifacts (AUTH and shard payloads).
- `doc_hash`/`doc_id` to bind frames and signatures to a specific ciphertext identity.
- Optional Shamir secret sharing to split custody of passphrases and signing seeds.

Threat-model sketches:

1) Single-custodian model
- One custodian holds the passphrase directly (no sharding) and can decrypt.

2) Sharded passphrase model
- N custodians each hold one passphrase shard; any T of N can reconstruct and decrypt.
- In a sealed envelope, decryptors cannot recover the signing seed from the manifest.

3) Split-trust model (dual-custodian)
- Group A holds passphrase shards (decryption capability).
- Group B holds signing-seed shards (ability to mint new signed AUTH/shard artifacts for a given
  `doc_hash` without decrypting).

Operational guidance:
- Avoid revealing whether decryption failed due to a wrong passphrase vs corrupted data (prefer a
  single generic failure message) to reduce oracle-style signal leakage.
- `doc_id`/`doc_hash` enable correlation across artifacts; privacy/anonymity is not a goal.

## Shard Set Identifier Rationale

Shard payload version 2 adds a signed `set_id` to each shard in a shard set.

Why this exists:
- Distinct shard sets for the same `doc_hash` and signing key can otherwise look mutually valid.
- With plain Shamir shares, any exact-threshold subset defines some polynomial, so mixed sets are
  not reliably detectable from share math alone.
- A signed `set_id` lets decoders reject mixed exact-threshold inputs before reconstruction or
  replacement-minting.

Operational guidance:
- When rotating or re-minting shards for the same backup, treat `set_id` as the shard-set identity.
- Do not mix custodial inventories across shard sets just because `doc_hash`, threshold, or share
  count match.

## Encoder/CLI Convenience Notes

Some implementations auto-resolve a base directory (for example, to the common parent) when none is
provided. This is a convenience behavior and not part of the on-disk format.

## Implementation Behavior Notes

`ethernity.encoding.chunking.reassemble_payload` is defined for
`FRAME_TYPE=MAIN_DOCUMENT` only. `AUTH` and `KEY_DOCUMENT` payloads are single-frame units and
should be decoded directly from their frame `data` bytes.

Some CLI flows expose an explicit unsigned-recovery override (for example, `--rescue-mode`, with
`--skip-auth-check` as a compatibility alias). This corresponds to rescue mode in `docs/format.md`
(Section 7.1), where signature verification bypass is allowed only under explicit operator
override. Structural, binding, and consistency checks still apply, and results are treated as
unauthenticated.

## Recovery Input Auto-Parsing Contract

When recovery input mode is auto-detected, implementations should apply this strict order:

1. If fallback section markers are present (`MAIN FRAME`, `AUTH FRAME`, shard markers), parse as
   fallback sections.
2. Otherwise, if all non-empty lines decode as QR payload frames, parse as payload mode.
3. Otherwise, if all non-empty lines are valid z-base-32 fallback lines, parse as fallback mode.
4. Otherwise, fail with an explicit invalid/ambiguous-input error.

Mixing payload and fallback lines in one input block is not supported.

## Resource Bounds Rationale (1 MiB v1 Profile)

The v1 profile uses a strict fail-closed bound set centered on a `1 MiB` ciphertext ceiling.

Design intent:
- Keep worst-case memory/CPU bounded for CLI recovery and frame parsing paths.
- Keep fallback-MAIN behavior aligned with single-frame recovery text output.
- Keep limits round and operationally predictable for implementation and testing.

Operational implications:
- Oversized artifacts are rejected instead of partially parsed.
- QR payload limits are intentionally conservative to avoid generating unreadable/high-density codes.
- Fallback parsing applies independent caps to source bytes, filtered line count, and normalized
  z-base-32 character count so malformed or adversarial text fails early.
- Input-admission policy is ciphertext-based: implementations may accept inputs larger than 1 MiB
  when pre-encryption compression allows the final ciphertext to stay within `MAX_CIPHERTEXT_BYTES`.

## Payload Compression Metadata (Manifest v1)

Stable v1 uses manifest metadata for payload storage coding without a version bump:
- `payload_codec`: required `"raw"` or `"gzip"`
- `payload_raw_len`: required only when `payload_codec == "gzip"`

Operational behavior:
- Compression is intended for the payload before envelope encryption.
- Recovery normalizes payload bytes via manifest metadata before manifest-file slicing/hash checks.
- This keeps existing extraction call sites stable and codec-agnostic.
- To avoid zip-bomb style inflation, gzip-coded manifests are capped by
  `MAX_DECOMPRESSED_PAYLOAD_BYTES` before decompression.

Compatibility note:
- Artifacts missing `payload_codec` are invalid under current stable-v1 decoder behavior.
- Implementations that do not support `gzip` metadata may fail to recover gzip-coded envelopes.

## QR Payload Transport Note

Version 1 supports two QR transport codecs as defined in `docs/format.md`:
- `raw` frame bytes (preferred for QR scan transport)
- unpadded `base64` text (for text-based workflows)

There is no manifest/envelope transport marker for QR payload codec in v1. Recovery boundaries
handle this by source type:
- byte-oriented scan sources can decode raw directly and fallback to base64 text decoding
- text sources remain strict unpadded base64 parsing

Implementations should not negotiate or introduce additional codecs in v1.

## Runtime Config Note

Current runtime config requires:
- `[defaults.backup].qr_payload_codec` with value `"raw"` or `"base64"`

Missing, empty, or unknown values are rejected by config loading.

## Passphrase Notes

The project commonly defaults to 24-word BIP-39 mnemonics in interactive flows. This is not a format
requirement.

Implementations often verify the BIP-39 checksum before attempting decryption; checksum failure is a
strong indicator of transcription error in the mnemonic.

Example (12 words):
```
abandon ability able about above absent absorb abstract absurd abuse access accident
```

## Shamir Operational Guidance

Any conforming Shamir implementation may be used as long as it matches the field parameters and
encoding rules in `docs/format.md`.

Python reference implementation:
- Secret sharing: `pycryptodome` (`Crypto.Protocol.SecretSharing.Shamir`).

Common operational guidance for shares:
- Shares are information-theoretically secure: T-1 shares reveal nothing.
- Share indices are not secret.
- Shares should be distributed to independent custodians.
- Never store multiple shares together.

## Path Normalization Rationale

Unicode paths can have multiple byte representations that render the same.

Example (visual string: "cafe"):
- NFC (composed): "caf" + U+00E9
- NFD (decomposed): "caf" + U+0065 + U+0301

Different operating systems use different forms (for example, macOS commonly uses NFD). Normalizing
to NFC ensures consistent matching across platforms.

NFC normalization does not solve case-folding differences on case-insensitive filesystems.
Operationally, avoid case-only path distinctions (for example, `Secrets.txt` vs `secrets.txt`) when
you expect cross-platform recovery or extraction.

Stable v1 also rejects drive-letter-prefixed paths (for example, `C:notes.txt`) to avoid
cross-platform ambiguity and extractor-specific drive semantics.

## Age Implementation Notes

Implementations should use a compliant age implementation rather than implementing age directly.

Python reference implementation:
- Encryption/decryption: `pyrage` (age passphrase recipient).

Scrypt parameters (work factor, salt, etc.) are defined by the age scrypt recipient stanza.

## Stable v1 Baseline Notes

Stable v1 profile baseline (normative requirements are in `docs/format.md`):
- Stable v1 decoders require manifest keys `input_origin`, `input_roots`, and `path_encoding`.
- Stable v1 decoders require array-based manifest `files` entries.
- Map-style manifest file-entry encodings are out-of-profile and are rejected by stable v1
  decoders.

CBOR payload evolution guidance:
- These payloads are CBOR maps. New optional fields should be added as new map keys.
- Decoders ignore unknown keys (as defined normatively in `docs/format.md`) to allow forward
  compatibility.
- Unknown keys are extension data only and are not trust-authoritative.
- Encoders should avoid emitting keys not defined in the format specification for a given version.

## Conformance Guidance (Non-normative)

The normative conformance requirements, including required decoder validation order and minimum
must-pass/must-reject scenarios, are defined in `docs/format.md` (Section 18).

Operational recommendation:
1. Use the Section 18 checklist as release gating for decoder conformance claims.
2. Keep implementation-specific test harness details outside the normative spec.

## Varint and CBOR Integer Encoding

The format uses unsigned varints (uvarint) only in the envelope and frame binary headers.

CBOR payloads (manifest, auth, shard) are CBOR maps:
- Integer fields inside these payloads use CBOR integer encoding (and should be canonical CBOR where
  required), not uvarint.
- When a signature is defined over a CBOR payload, the signed bytes are the canonical CBOR encoding
  of that payload (with the signature field omitted), not a separate uvarint re-encoding of fields.
