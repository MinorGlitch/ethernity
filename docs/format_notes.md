# Ethernity Format Notes (Non-normative)

This document contains rationale and operational guidance that is intentionally excluded from the
[core format specification](format.md). Canonical extension export and maintenance requirements are
defined separately in the
[v1.2 extension operations and publication profile](extension_publication_profile.md).

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
- A separately stored chain-bound kit supplies an out-of-band trust anchor for the root identity,
  root signing key fingerprint, and expected head. A manually recorded expected head can pin
  freshness without authenticating root identity. Neither is part of content import itself.
- Two operators can append independently from the same head and create valid forks. Supplying both
  conflicting branches is an ambiguity and fails closed, but either branch can validate in isolation.
  `Latest` therefore always means latest among the carriers supplied to that operation. Browser
  recovery requires a trusted-kit pin, a manually entered expected head, or an explicit
  freshness-unknown acknowledgement before using that target. The current release deliberately has
  no global ledger or online coordination requirement.

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

Machine-readable ciphertext, AUTH frames, and signed shard payloads remain authoritative. The v1.2
operations profile also requires exact validation of extractable fallback sections before publish
and append so the fallback bytes cannot silently diverge from their authenticated carrier.

Text extraction cannot prove physical visibility or legibility, and it is not a signed publication
inventory. In particular, root envelope v1 cannot prove that an entirely absent shard role was ever
published. The operations profile defines the resulting fail-closed and unknowable cases.

## Publication Recovery

`.chain.lock` is intentionally permanent. Its existence does not mean a process is running; the
kernel lock held through the open file handle is the concurrency signal and disappears if that
process dies. Inside a canonical backup, a leftover `.staging-*` directory is likewise not
something to delete by hand. `ethernity run doctor` first authenticates the published chain and
checks transaction snapshots and ancestry. With `--repair --yes`, it can remove a staging duplicate
whose final directory is already the authenticated committed head. It refuses to remove
unjournaled staging because a live publisher may still own it, and it refuses to resume journaled
staging because transaction version 1 does not authenticate the original optional-carrier
publication policy. Repair moves such an authenticated, snapshot-matching unpublished transaction
to a sibling quarantine instead; this preserves the staged carriers and frees the canonical
extension namespace for a fresh Add Files operation. Promoted transaction records are inspected
against the authenticated chain and require no repair when their recorded snapshot still matches.

A scan-mode loose output root is a dedicated generated workspace, not a canonical backup root, so
Doctor does not operate on it. If publication was interrupted before an `extension-*` directory
was promoted, first confirm that no Add Files process is still running, then abandon the entire
loose output folder or choose another empty output folder. Do not remove individual hidden entries.
If an `extension-*` directory was promoted, preserve the completed bundle.

Directory durability is not uniformly exposed by every operating system and filesystem. Extension
publication therefore requires flushed regular files, a transaction journal, one persistent
advisory lock, authenticated head revalidation, and a same-filesystem atomic rename on every
platform. Compaction uses the same source-chain lock, head revalidation, file flushing, and atomic
rename but, because it creates a separate standalone backup, does not write an extension
transaction journal. POSIX implementations additionally require directory `fsync`; Windows
continues with its strongest portable guarantee when Python cannot open a directory for flushing.
Ordinary backup, mint, and restore remain outside the journaled durability guarantee.

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
standalone root when a chain is near any limit. KDF admission is a runtime safety policy, not a
stable-v1 format restriction. Desktop and browser recovery parse every public scrypt stanza before
starting a KDF, enforce both per-stanza and cumulative work ceilings, and run approved work in
disposable workers. Normal desktop recovery accepts through `log_n = 19`; `log_n = 20` requires the
explicitly named resource-intensive compatibility recovery override. Values above `20` and
cumulative work above the compatibility ceiling are always rejected. Browser recovery retains its
more conservative automatic threshold. Cancellation, CPU/memory ceilings, or wall-time expiry
terminate the active worker rather than leaving an in-process KDF running.

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

Version 1 supports two QR transport codecs as defined in the core format specification:
- `raw` frame bytes (preferred for QR scan transport)
- unpadded `base64` text (for text-based workflows)

There is no manifest/envelope transport marker for QR payload codec in v1. Recovery boundaries
handle this by source type:
- byte-oriented scan sources can decode raw directly and fallback to base64 text decoding
- text sources remain strict unpadded base64 parsing

Implementations should not negotiate or introduce additional codecs in v1.

## QR/PDF Scan Parser Isolation Note

The CLI treats each PDF or image carrier as hostile input. Path traversal and publication-layout
checks happen before parsing. Each admitted file is then parsed and QR-decoded in a fresh spawned
worker with memory, CPU, wall-time, PDF-page, embedded-image, pixel, decoded-payload, and IPC-output
ceilings. The complete scan also has file-count, aggregate payload, and wall-time ceilings.

Workers are disposable: timeout, resource exhaustion, parser failure, task cancellation, or source
replacement terminates the subprocess. Parser objects and decoded image state never return to the
main application; only bounded QR payload bytes cross the process boundary. Platforms that cannot
install or observe the required worker limits fail closed instead of silently parsing in-process.

## Runtime Config Note

Current runtime config requires:
- `[defaults.backup].qr_payload_codec` with value `"raw"` or `"base64"`
- `[defaults.extend].qr_payload_codec` with value `"raw"` or `"base64"` when present

Missing, empty, or unknown values are rejected by config loading.

## Passphrase Notes

The project commonly defaults to 24-word BIP-39 mnemonics in interactive flows. This is not a format
requirement.

Producers canonicalize whitespace only when the text is a checksum-valid BIP-39 mnemonic. Recovery
tries the supplied string exactly first, then may retry its distinct canonical single-space BIP-39
form. Word-list-shaped custom strings with an invalid checksum remain exact non-BIP-39 passphrases.

Example (12 words):
```
abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about
```

## Shamir Operational Guidance

Any conforming Shamir implementation may be used as long as it matches the field parameters and
encoding rules in the core format specification.

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

## Varint and CBOR Integer Encoding

The format uses unsigned varints (uvarint) only in the envelope and frame binary headers.

CBOR payloads (manifest, auth, shard) are CBOR maps:
- Integer fields inside these payloads use CBOR integer encoding (and should be canonical CBOR where
  required), not uvarint.
- When a signature is defined over a CBOR payload, the signed bytes are the canonical CBOR encoding
  of that payload (with the signature field omitted), not a separate uvarint re-encoding of fields.
