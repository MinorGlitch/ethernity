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

## Encoder/CLI Convenience Notes

Some implementations auto-resolve a base directory (for example, to the common parent) when none is
provided. This is a convenience behavior and not part of the on-disk format.

## Recovery Input Auto-Parsing Contract

When recovery input mode is auto-detected, implementations should apply this strict order:

1. If fallback section markers are present (`MAIN FRAME`, `AUTH FRAME`, shard markers), parse as
   fallback sections.
2. Otherwise, if all non-empty lines decode as QR payload frames, parse as payload mode.
3. Otherwise, if all non-empty lines are valid z-base-32 fallback lines, parse as fallback mode.
4. Otherwise, fail with an explicit invalid/ambiguous-input error.

Mixing payload and fallback lines in one input block is not supported.

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

## Age Implementation Notes

Implementations should use a compliant age implementation rather than implementing age directly.

Python reference implementation:
- Encryption/decryption: `pyrage` (age passphrase recipient).

Scrypt parameters (work factor, salt, etc.) are defined by the age scrypt recipient stanza.

## Versioning Notes

If a future release requires backward compatibility for a changed payload format, versions should be
bumped and older versions kept decodable.

CBOR payload evolution guidance:
- These payloads are CBOR maps. New optional fields should be added as new map keys.
- Decoders typically ignore unknown keys to allow forward compatibility.
- Encoders should avoid emitting keys not defined in the format specification for a given version.

Backward compatibility guidance:
- Pre-release encodings that used CBOR lists/arrays are not supported by current decoders.

## Varint and CBOR Integer Encoding

The format uses unsigned varints (uvarint) only in the envelope and frame binary headers.

CBOR payloads (manifest, auth, shard) are CBOR maps:
- Integer fields inside these payloads use CBOR integer encoding (and should be canonical CBOR where
  required), not uvarint.
- When a signature is defined over a CBOR payload, the signed bytes are the canonical CBOR encoding
  of that payload (with the signature field omitted), not a separate uvarint re-encoding of fields.
