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
- This separation applies to re-minting auxiliary artifacts for an existing document identity. It
  does not make Group B an additional approver for an extension append; the extension authority
  contract below is different.

Operational guidance:
- Avoid revealing whether decryption failed due to a wrong passphrase vs corrupted data (prefer a
  single generic failure message) to reduce oracle-style signal leakage.
- `doc_id`/`doc_hash` enable correlation across artifacts; privacy/anonymity is not a goal.

## Extension Freshness Model

Extension replay authenticates the chain prefix present in the supplied recovery material. It proves
that the supplied extensions form a valid, root-authorized ancestry from the selected root backup,
but it does not prove that no later extension was ever created.

Operational implications:
- A stale recovery set that contains root plus extensions `1..N` can be indistinguishable from a
  complete chain whose latest head is `N`.
- Missing, corrupt, forked, or unauthenticated supplied extensions still fail closed; the limitation
  is only absence detection for material that was not supplied.
- Absolute freshness requires an additional signed head marker, external registry, or other
  out-of-band freshness source. That is outside the current content-import profile.
- Two operators can append independently from the same head and create valid forks. Supplying both
  conflicting branches is an ambiguity and fails closed, but either branch can validate in isolation.
  `Latest` therefore always means latest among the carriers supplied to that operation. The current
  release deliberately has no global ledger or online coordination requirement.

## Extension Authority and Lifecycle

An appendable root is unsealed: its encrypted manifest contains the chain signing seed. Anyone who
has the root carriers and can unlock that manifest can both recover data and sign a valid extension.
Signing-key recovery sheets are redundant custody copies of the signing seed, not a second factor or
an independent approval step.

Rebuild/compaction preserves the passphrase and signing seed. It shortens the recovery chain into a
new standalone checkpoint, but it does not rotate credentials, revoke older authority, or create a
new security boundary. After credential compromise, or when intentional rotation is needed, recover
the desired files and create a New Backup with new credentials, then retire the old carrier set.

Add Files is add-or-replace rather than filesystem synchronization. A matching path is replaced and
an omitted path remains in logical state. A rename adds the new path without removing the old one.
To remove or truly rename content, recover the desired state, create a New Backup that omits the old
path, and retire every old paper and digital carrier whose historical copy must no longer be usable.

## Published Fallback Assurance

Machine-readable ciphertext, AUTH frames, and signed shard payloads remain authoritative. The
extractable fallback text layer in each fallback-bearing canonical root or extension PDF is
nevertheless checked immediately after rendering, before publish, and again during later
append/discovery validation of a canonical published head. Designated sections must canonical-decode
in order and match the exact expected MAIN/AUTH or KEY frame bytes one-to-one.

This binds one extractable fallback encoding to one authenticated carrier identity. PDF text
extraction cannot prove that text is physically visible, on-page, unclipped, or comfortably legible,
so print inspection remains separate. The check is not a signed publication manifest and does not
prove that every carrier ever produced, or a globally latest head, is present.

Canonical root creation/publish and later append apply the audit to `recovery_document.pdf` and to
every canonical-named root shard PDF. A present canonical shard role is filename-enumerable, so its
declared `1..share_count` set can fail closed on gaps or inconsistent signed payloads. An entirely
absent shard role is different: the root has no signed publication manifest recording that such a
set was created, so absence is unknowable rather than proof of completeness. Renamed matching-root
PDF shards can be audited individually, but their names cannot establish a complete custody set.
Images and unrelated or foreign-root carriers under non-canonical names are ignored by the PDF
fallback audit; canonical-pattern names remain fail-closed.

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

The current restore surface does not expose an unsigned-recovery override. Internal
recovery code still models unsigned recovery as a fail-closed implementation state for legacy tests
and controlled callers, but shipped commands require authenticated recovery inputs. Structural,
binding, and consistency checks still apply to all recovery modes.

## Recovery Input Auto-Parsing Contract

When recovery input mode is auto-detected, implementations should apply this strict order:

1. If fallback section markers are present (`MAIN FRAME`, `AUTH FRAME`, `SHARD FRAME`, `KEY FRAME`), parse as
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

The extension profile adds chain-wide limits because otherwise individually valid documents can
accumulate unbounded recovery work. A chain stops at 128 total documents, 64 MiB aggregate
ciphertext, and 256 MiB cumulative decoded inline chunks. Rebuild/compaction creates a fresh
standalone root when a chain is near any limit. Browser KDF admission is a runtime safety policy,
not a stable-v1 format restriction; desktop recovery retains age's full legacy compatibility.
The browser parses every public scrypt stanza before starting a KDF, rejects factors above its
supported ceiling. A separate explicit action is required before either a profile above
`log_n = 18` or cumulative work above eight `log_n = 18` documents is attempted. Approved KDF work
runs one document at a time in a cancellable Worker. This keeps `log_n = 19` and `20` recovery
available without letting scanned input silently start a 512 MiB or 1 GiB allocation, or a long
sequence of otherwise individually acceptable KDFs.

Append deduplication does not require retaining every historical decoded chunk. Writers can retain
the latest logical state's chunk bytes plus the set of all earlier chunk identifiers. If new input
returns to old content (for example A to B to A), its bytes establish the matching identifier and the
new extension references the historical chunk instead of emitting it again.

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

## QR/PDF Scan Parser Isolation Note

The current CLI scan implementation parses PDF and image carriers in-process through the centralized
`ethernity.qr.scan` boundary. That boundary rejects symlinked scan inputs, applies backup-export
layout rules before recursive scans, enforces explicit file/PDF/image/decoded-payload budgets, and
hands decoded QR bytes back to the normal frame/profile validators, but it is not an OS sandbox
around the PDF/image parser libraries.

Operational guidance:
- Treat scans from unknown bulk sources as untrusted file parsing and run the CLI in an OS sandbox,
  container, or equivalent restricted environment when that threat model matters.
- Prefer scanned artifacts generated by Ethernity or individually reviewed recovery carriers over
  arbitrary directory trees.
- A future scanner-worker split should preserve the current `QrDecoder` adapter boundary while
  moving PDF/image parser execution into a constrained subprocess with resource limits.

## Runtime Config Note

Current runtime config requires:
- `[defaults.backup].qr_payload_codec` with value `"raw"` or `"base64"`
- `[defaults.extend].qr_payload_codec` with value `"raw"` or `"base64"` when present

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
