# Age-Based Paper Backup Plan

This document captures the agreed plan for a paperback-inspired backup system
that stores age-encrypted payloads on paper (QR + text fallback) with optional
key sharding.

## Goals
- Provide paper-friendly backups of age-encrypted data.
- Support creator-absent recovery (e.g., wills).
- Make sharding optional and configurable (default is no sharding).
- Use age passphrase mode for encryption.
- Keep QR density and error correction configurable.
- Always include a human-readable fallback (z-base-32) in the recovery document.

## Non-goals (for initial scope)
- No robust automated QR scanning in v0 (optional scan path if deps installed).
- No GUI in v0 (CLI + config only).
- No custom cryptography beyond standard primitives.

## Key Decisions and Defaults
- Default backup uses a generated mnemonic passphrase when none supplied; key material is printed in the recovery document (no separate key card by default).
- Sharding is optional and passphrase-only; shard documents are separate outputs.
- Sealed flag is stored in the manifest/envelope; signature enforcement uses it.
- doc_id = BLAKE2b(ciphertext), truncated to 16 bytes (printed and embedded in frames).
- Paper size default is A4; Letter preset supported via config.
- QR payloads are binary frames by default; base32-in-QR is deferred.
- Text fallback is always present in the recovery document and uses z-base-32.
- Config format is TOML; CLI supports flags + wizard, and subcommands auto-launch wizards when no inputs are provided.
- Signature verification is strict by default; allow a relaxation flag for recovery.

## Threat Model and Recovery Goals
- Up to n-1 shard holders may be malicious or compromised.
- Recovery must detect forged or mismatched shards/documents when possible.
- Recovery works without the original creator present.
- Forgery detection assumes at least one honest shard remains unmodified.

## Crypto Design

### Modes
1) Passphrase Mode
   - User-supplied passphrase (no key doc needed).
   - Or generated passphrase (recovery doc by default; shards optional).

### What Gets Sharded
- Only key material is sharded, not the ciphertext.
- Passphrase bytes (generated or user-supplied) -> Shamir shards.
- No-sharding mode stores the passphrase in the recovery document (equivalent to k=1, n=1).

### Forgery Detection and Binding (Implemented)
- Generate a per-backup Ed25519 signing key pair.
- doc_hash = BLAKE2b(ciphertext, 32 bytes).
- Auth frame payload (CBOR array):
  - [auth_version, doc_hash, sign_pub, signature]
  - signature = Sign("ETHERNITY-AUTH-V1" || doc_hash)
- Shard payload includes sign_pub + doc_hash and signature:
  - signature = Sign("ETHERNITY-SHARD-V1" || doc_hash || shard_index || shard_share_bytes)
- sign_pub is stored in three places:
  - auth frame, shard payload, and recovery document (z-base-32).
- sign_priv is stored only in the recovery document when unsealed.
- Strict verification by default; recovery can relax with `--allow-unsigned`.

### Sealed Backups
- Sealed option omits the signing private key from the recovery document.
- New shards cannot be signed later, so they will be rejected on recovery.
- Enforcement uses signature verification (strict by default).

## Serialization and QR Framing

### Frame Format (binary payload)
```
MAGIC(2) | VERSION(varint) | TYPE(1) | DOC_ID(16) | IDX(varint) | TOTAL(varint) |
LEN(varint) | DATA... | CRC32(4)
```
- TYPE distinguishes: main-doc chunk, key-doc chunk, checksum, etc.
- DOC_ID allows early rejection of mixed documents.
- CRC32 gives fast corruption detection for manual entry.
- AUTH frame type for signature payloads (one per document).

### Encoding Strategy
- Primary QR encoding is binary frames (byte mode, max density).
- Base32 text inside QR is deferred.
- Text fallback:
  - z-base-32 of the same framed payload, printed in the recovery document.
  - Grouped in 4s, line-wrapped for readability.

### Chunking Defaults
- Text fallback is stored as labeled AUTH + MAIN blocks in the recovery document.
- Default chunk_size is 200 bytes (evenly distributed across QR frames).
- Fallback line length defaults to auto (line_length = 0) with line_count = 10 in presets.
- Users can tune:
  - chunk_size_bytes
  - fallback_line_length
  - fallback_line_count

## Encrypted Envelope
- Wrap plaintext in an envelope before age encryption.
- Layout:
  - MAGIC ("AY") | VERSION | MANIFEST_LEN(varint) | MANIFEST_BYTES | PAYLOAD_LEN(varint) | PAYLOAD_BYTES
- Manifest encoding: CBOR arrays (fixed field order).
- Recovery flow: decrypt -> parse envelope -> restore files using manifest data.
- Manifest layout (CBOR array):
  - [format_version, created_at_epoch, sealed, prefixes, files]
  - prefixes: ["", "common/dir", ...]
  - files: [prefix_idx, suffix, size_bytes, sha256_bytes, mtime_epoch_int]
- Multi-file inputs:
  - Store paths relative to a base directory (auto common parent unless overridden).
  - Error on duplicate relative paths.
  - Future: add dedupe mode for collisions (rename/suffix).
  - Future: preserve file permissions alongside mtime.
  - Future: prefix-table heuristic (include prefixes only if net savings > overhead).

### QR Settings
- Error correction: configurable (L/M/Q/H).
- Max grid per page: configurable (auto-fill until max, then new page).
- QR size and margins configurable.

## Document Types

### Main Document
Contains:
- QR codes only (ciphertext split across frames).
- doc_id (printed and in QR frames; BLAKE2b(ciphertext) truncated to 16 bytes).
- No text fallback.

### Shard Documents (passphrase mode)
One per shard:
- doc_id and shard index/total.
- shard payload (QR + z-base-32 fallback), including sign_pub/doc_hash/signature.

### Recovery Document
Contains:
- Full z-base-32 fallback for the ciphertext (single stream, paginated).
- Key material needed for recovery (passphrase).
- doc_id and recovery instructions.

## Layout and UX
- A4 default; other sizes via config.
- Auto-fill QR grid with configurable max columns/rows.
- Separate QR document (no fallback) and recovery document (fallback + keys).
- Clear sections:
  - Main doc: header, QR grid, doc_id.
  - Recovery doc: key material, instructions, text fallback.
  - Shard docs: shard info, QR, text fallback.
  - Simple instructions and warnings for recovery and storage.

## Configuration (TOML)
Key sections to include:
- [template] main QR template path
- [recovery_template] recovery template path
- [shard_template] shard document template path
- [context] paper size, margins, header styles, QR grid, fallback layout, instructions
- [qr] error correction, scale, border, colors, shapes, version/mask
- Crypto/sharding/output options are currently driven by CLI flags (TOML hooks TBD).

## CLI Plan
- `backup`: encrypt + generate PDFs (wizard auto-runs when no inputs on TTY).
- `recover`: ingest fallback/frames/scan + reconstruct + decrypt (wizard auto-runs when no inputs on TTY).
- `demo`: render a sample PDF using current settings.
- `expand-shards`: generate new shards (if not sealed).
- `reprint`: regenerate PDFs from stored data.
- Support both flags and interactive prompts.
- Add `--allow-unsigned` to relax signature verification (default strict).

## Implementation Stack
- age CLI via subprocess (spec-compliant).
- Shamir: PyCryptodome (`Crypto.Protocol.SecretSharing.Shamir`, GF(2^8), n<=255).
- QR: segno (pure Python, byte mode support).
- PDF: fpdf2 (pure Python, lightweight).
- Templates: Jinja2 (TOML-backed layout specs).
- Envelope/manifest: cbor2.
- Config: tomllib / toml.
- CLI: Typer + Rich.
- Passphrase generation: python-mnemonic (BIP39 wordlists).

## Project Layout (Current)
- `ethernity/`: Python package root.
- `ethernity/cli/`: CLI package root.
- `ethernity/cli/app.py`: Typer app entrypoint.
- `ethernity/cli/commands/`: Typer subcommands (backup/recover/demo/manpage).
- `ethernity/cli/flows/`: backup/recover flows + prompt helpers.
- `ethernity/cli/core/`: shared CLI helpers (types/plan/crypto/log).
- `ethernity/cli/io/`: input/output helpers (frames/files).
- `ethernity/cli/keys/`: recovery key verification helpers.
- `ethernity/cli/ui/`: Rich UI, prompts, summaries/debug.
- `ethernity/crypto/age_cli.py`: age interface module (subprocess/pty).
- `ethernity/crypto/passphrases.py`: mnemonic passphrase generation.
- `ethernity/encoding/framing.py`: QR frame encode/decode (magic/version/type/doc_id/idx/total/len/CRC).
- `ethernity/encoding/chunking.py`: chunk sizing, z-base-32 fallback formatting.
- `ethernity/qr/codec.py`: QR generation helpers (segno integration).
- `ethernity/qr/scan.py`: QR scanning helpers (zxing-cpp + PIL).
- `ethernity/render/pdf_render.py`: PDF rendering orchestrator (Playwright).
- `ethernity/render/layout.py`: Layout calculations + fallback line generation.
- `ethernity/render/templating.py`: Jinja2 rendering for HTML templates.
- `ethernity/formats/envelope_types.py`: envelope manifest types + CBOR helpers.
- `ethernity/formats/envelope_codec.py`: envelope encode/decode + payload builders.
- `ethernity/config/loader.py`: TOML config loader + QR parsing.
- `ethernity/config/installer.py`: default config/template installer.
- `ethernity/templates/`: layout templates (`.html.j2`) for main/recovery/shard docs.
- `ethernity/config/`: preset TOML configs (A4 default, Letter optional).
- `demo/render_demo.py`: sample PDF demo.
- `demo/scan_demo.py`: scan demo harness.
- `ethernity/sharding.py`: Shamir split/join for passphrase shards.
- `tests/`: unit/integration/end-to-end tests.

## Dependencies (uv)
- cbor2
- mnemonic
- typer
- rich
- shellingham
- pycryptodome
- segno
- fpdf2
- jinja2
- pillow (optional, QR scan helpers)
- pypdf (tests/inspection)
- zxing-cpp (optional QR scanning)
- coverage (tests)
- playwright (HTML -> PDF rendering)

## External Requirements
- age CLI available on PATH (used via subprocess).

## `pyproject.toml` Status (uv init)
- uv init completed; dependencies are recorded in `pyproject.toml`.
- Current requires-python is `>=3.13`.
- Console script entry: `ethernity = ethernity.cli:main` (packaged templates/configs).

## Validation Plan
- Deterministic unit tests for:
  - framing encode/decode
  - chunking and reassembly
  - z-base-32 fallback with CRC
  - envelope/manifest parsing
  - sharding encode/decode
- Integration tests:
  - CLI backup/recover flows
  - PDF rendering smoke tests
- End-to-end tests:
  - CLI backup -> recover plaintext
  - shard recovery (frames + fallback)
  - mixed-doc rejection (doc_id mismatch)
- Manual scan tests on printed samples.

## Open Questions / To Decide Later
- Confirm PyCryptodome version pinning and compatibility.
- Decide whether to include per-shard AEAD wrapping (separate key storage).
- Decide on base32-in-QR encoding mode + UX.
- Define expand-shards workflow.

## Current Defaults (Config)
- doc_id length: 16 bytes (BLAKE2b ciphertext hash).
- chunk size: 200 bytes (default chunker).
- fallback line_length: auto (0), line_count: 10.
- QR error correction: Q; binary QR payloads.
- signature verification: strict by default (planned `--allow-unsigned` override).
- output naming: `backup-{doc_id}/qr_document.pdf`, `backup-{doc_id}/recovery_document.pdf`,
  shards `shard-{doc_id}-{i}-of-{n}.pdf`.

## Next Steps (Current)
- Decide on base32-in-QR support and config knobs.
- Improve QR scan robustness (PDF/image pipelines) if needed.
- Add expand-shards/reprint commands (sealed enforcement for those flows).
- Update README with install + usage (pipx, `ethernity` examples).

## Implementation Status (Current)
- Implemented:
- age CLI wrapper (passphrase encrypt/decrypt)
  - framing encode/decode + CRC
  - chunking + z-base-32 fallback encoding/decoding
  - envelope + manifest (CBOR arrays, prefix table, sha256 raw bytes, mtime int)
  - QR generation (segno) + PDF rendering (fpdf2)
  - templates + config presets (A4/Letter)
  - separate QR document + recovery document outputs
  - shard document outputs (passphrase mode)
  - CLI `backup`/`recover` (Typer + Rich, flags + wizard auto-launch, quiet/version, manpage/completions)
  - balanced chunk sizing (evenly filled QR density)
  - multi-file inputs (recursive directories, base-dir relative paths, duplicate path guard)
  - passphrase sharding (Shamir split/join, shard payload format v3)
  - packaging (`ethernity` package + console script + package data)
  - tests: unit, integration, end-to-end (CLI + sharding)
- Partly implemented:
  - QR image/PDF scanning (requires optional decoder deps; PDF scanning not robust)
  - sealed flag stored in manifest/envelope (enforcement TBD for reprint/expand)
- Not implemented:
  - base32-in-QR encoding mode
  - expand-shards/reprint commands (incl. sealed enforcement)
  - prefix-table heuristic (include prefixes only if net savings > overhead)
