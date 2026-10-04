**Rendering engine audit, 2026-10-04**

The consolidation has improved the architecture, and the tested default layouts are healthy.
Five confirmed issues remain. The largest weakness is output validation: it checks extraction,
operator counts, and renderer proofs more thoroughly than it checks the meaning and visibility
of the final printed artifact. Two findings are P1; three are P2.

This audit used the current working tree, including its existing uncommitted and untracked
changes. Production source, tests, generated bundles, and visual fixtures were left unchanged.
Experiments used temporary files. This report is the only repository file added by the audit.

**1. P1: QR validation can approve a page whose printed QR cannot be recovered.**

The production validator calls the recovery scanner, which decodes embedded image resources.
It does not decode the final composed page. Image placement checks confirm coordinates but
cannot detect an image being covered or its visible appearance being changed by transparency.

A supported configuration, `QrConfig(dark=(0, 0, 0, 3), light="white")`, rendered a Sentinel main
document that passed production validation. Whole-page QR scans decoded zero payloads at 144,
200, 300, and 600 DPI. Its QR was almost invisible on the rendered page. The color guard accepts
any positive luminance difference, including this extremely faint appearance.

Separately, fault injection appended an opaque white rectangle over every page of a valid main
document. All five designs still passed production validation with their original proofs,
while their composed pages contained zero decodable QRs. This demonstrates the validator gap;
ordinary default layouts did not spontaneously generate covered pages.

Sources: [production QR check](/Users/alstoyan/ethernity/src/ethernity/render/validation.py:100),
[embedded-image scanner](/Users/alstoyan/ethernity/src/ethernity/qr/scan.py:323),
[image placement check](/Users/alstoyan/ethernity/src/ethernity/render/pdf_content.py:58),
[color guard](/Users/alstoyan/ethernity/src/ethernity/qr/codec.py:104).

Fix direction: validate QR usability in the final page composition and enforce a meaningful
print contrast policy. Preserve the efficient resource scanner for its recovery use case;
render verification has different requirements.

**2. P1: Recovery validation can approve the wrong printed passphrase.**

Literal passphrase validation searches for its words, in order, anywhere in the extracted PDF
text. It does not require those words to come from the passphrase value. The painted-text check
counts text operators without checking their content, position, or visibility.

For Archive, Forge, Ledger, and Maritime, I used the passphrase `Keep it separate` and replaced
every printed passphrase value with `wrong words`, preserving the original proofs and number
of text operators. All four outputs passed because the intended words appeared in the
instructions. Sentinel reproduced the same failure with `RECOVERY DOCUMENT`: replacing only
the monospaced passphrase value passed because the heading supplied the expected words.

An independent fault injection set the PDF text rendering mode to invisible (`3 Tr`). All five
recovery designs still validated, despite having no visible passphrase or fallback text.
Rendered page inspection confirmed the missing text.

Sources: [whole-document word matching](/Users/alstoyan/ethernity/src/ethernity/render/validation.py:171),
[painted-text counting](/Users/alstoyan/ethernity/src/ethernity/render/pdf_content.py:26).

Fix direction: give required values explicit semantic regions in the measured plan and compare
their actual visible text with the structured recovery metadata. Headers and instructions must
not satisfy a secret-value check. The same visibility checks should cover fallback text.

**3. P2: Global text parsing rejects valid custom passphrases.**

The validator infers numbered JSON parts from a regular expression over the entire document,
before honoring the literal printing mode. A valid literal passphrase such as `1/2 "hello"`
is consequently treated as an incomplete multipart encoding. All five designs rendered the
value but rejected the resulting document.

I also reproduced this through the real CLI backup workflow. A backup of a small temporary file
with `--recovery-count 0 --passphrase '1/2 "hello"' --design sentinel --yes --json` passed task
validation and then failed with `rendered recovery document has incomplete recovery passphrase
parts`.

There is a related collision in fallback validation: the literal passphrase `Main frame` was
misidentified as an extra `MAIN FRAME` section heading in Archive, Forge, Ledger, and Sentinel.
Maritime accepted that particular example. A recovery value should not become a structural
delimiter simply because its text resembles one.

Sources: [JSON-parts inference](/Users/alstoyan/ethernity/src/ethernity/render/validation.py:157),
[global fallback-heading matching](/Users/alstoyan/ethernity/src/ethernity/render/proofs.py:589).

Fix direction: carry the resolved printed mode through pagination and validate only the
designated passphrase or fallback regions. Include literal values resembling part numbers and
section headings in regression coverage.

**4. P2: Production kit validation ignores essential QR chunk order.**

The validator compares decoded QR payloads with `Counter`, which checks payload identity and
multiplicity but discards order. The proof records intended order; it does not establish which
payload was actually painted in each labeled position.

I swapped the first two payload chunks after the shell during QR image generation. All five
kit designs passed production validation. Whole-page scans recovered all 16 expected payloads
in the injected, incorrect order. The visual matrix's ordered comparison caught the difference.

The order requirement is functional. The real default kit produced 56 readable QRs and its
reconstructed JavaScript loader successfully opened the kit. Swapping its first two payload
chunks made the same loader fail during decompression. A direct check of the current bundle
confirmed that the reordered chunks no longer reconstructed a valid gzip stream.

Source: [unordered payload comparison](/Users/alstoyan/ethernity/src/ethernity/render/validation.py:103).

Fix direction: bind each decoded payload to its actual page position and verify kit reading
order. Keep main-document scanning unordered, as its printed instructions permit. This rule
belongs to the kit role, rather than being imposed on every QR document.

**5. P2: A rejected standalone kit can overwrite an existing valid PDF.**

The standalone kit workflow renders directly to the requested destination and validates
afterward. Validation failure occurs after the previous file has already been replaced.

I copied a valid kit PDF to a temporary destination, then called the real kit workflow with
`QrConfig(dark="#fefefe", light="white")`. The workflow raised `rendered recovery kit has no
usable QR payloads`, but the original PDF was gone. An eight-page rejected PDF remained at the
destination. No painter or filesystem failure had to be injected.

Sources: [render followed by validation](/Users/alstoyan/ethernity/src/ethernity/workflows/kit/service.py:175),
[direct destination write](/Users/alstoyan/ethernity/src/ethernity/render/direct_pdf/surface.py:281).

Fix direction: render and validate in a sibling temporary file, then atomically replace the
destination after success. Directory staging in the backup workflow already provides a stronger
publication boundary; the standalone kit needs equivalent file-level protection.

**Architecture assessment**

The recent consolidation respects the important boundaries. The document planner owns assembly
and proof aggregation through typed page builders; design-specific artwork and geometry remain
local. Shared fallback fitting receives explicit typography and spacing. The shared classic
passphrase builder is limited to the genuinely common Ledger/Maritime continuation structure.
Sentinel footer and QR separation use explicit component membership. The removed envelope,
DOCX, storage-helper, and dependency paths have no remaining runtime callers in the inspected
tree.

I did not find evidence that more broad design merging would improve this engine. The next work
should strengthen the existing validation and publication boundaries. Adding compatibility
wrappers or a second validator would make ownership less clear.

The earlier threshold-one shard instructions, head-anchor identity, shrink retry behavior,
descender handling, QR payload identity checks, and point-based character spacing passed their
current regression coverage. The earlier validation finding is only partially resolved:
operator omission and unique-value substitution are detected, but visibility and semantic
identity remain vulnerable to the cases above.

**Verification and limits**

- Rendering unit suite: 431 tests and 579 subtests passed, including minimum and future paper
  geometry, maximum shard data, long passphrase continuations, layout proofs, and output checks.
- QR and packaging unit suites: 80 tests and 31 subtests passed.
- Integration and E2E suites: 63 tests and 95 subtests passed.
- Fresh visual matrix: 64 cases, 135 pages, and 390 physical QR payloads. Embedded and composed
  QR identity/order checks passed; no reported overlaps, layout overflow, or Poppler warnings.
- Rendered samples from all five designs were visually inspected. An independent glyph-outline
  check of 1,748 embedded-font text lines found no horizontal escapes in those standard cases;
  that extra outline check excluded core PDF fonts.
- Ruff lint and format, Pyrefly, typos, lock consistency, and whitespace checks passed. Pyrefly
  reported zero errors and 54 warnings. The previously built consolidation wheel still matched
  the current source package contents; a fresh wheel was not built for this audit.
- The real default kit was rendered, scanned in page order, reconstructed, and exercised through
  its actual JavaScript loader in a Node harness. This checks loading and decompression, rather
  than a complete browser UI recovery session.

Total: 574 tests and 705 subtests passed. Passing tests and the standard visual matrix do not
cover the deliberately injected failures or all custom inputs described in these findings.

Execution was on macOS with the installed dependency versions. Linux/Windows were not executed
locally, and the entire unrelated application unit suite was not rerun. Obsolete unused gzip
artifacts with a different alphabet were excluded: the current packaged bundles and current
builder agree, and the default reconstruction succeeded.
