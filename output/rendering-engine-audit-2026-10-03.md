Rendering engine audit

The direct PDF architecture is worth keeping. Explicit document inputs, a small PDF surface, measured component plans, bounded pagination, and verification of extracted fallback data are sound foundations. The implementation is not yet as reliable as its proof and validation interfaces suggest. I reproduced misleading security instructions, a document with the wrong printed role, text fitting failures, and validation that accepts unusable or incomplete output.

This audit covers the current working tree on 3 October 2026, including uncommitted changes and new rendering modules, rather than only committed code. HEAD was `509a377516c4aab04ab11cd52fb3b61114ef200a`. I reviewed the five designs, shared rendering components, dispatch and input construction, proof validation, rendering callers, and visual QA. I also checked generated pages and exercised backup, recovery, extension, kit, and shard workflows. No implementation files were changed.

P1 below means a correction should precede relying on the affected output for recovery or security decisions. P2 means a correctness or verification gap requiring a focused fix. P3 means a lower priority contract or maintenance issue. Findings distinguish failures produced by supported inputs from fault injection used to test the validators.

1. **P1: Production validation can accept a PDF with no usable QR codes or missing recovery content.**

   The generic validator compares renderer supplied proof metadata with render inputs, then checks that the PDF has pages. Layout validation occurs only inside `if inputs.render_fallback`. Consequently, main documents and other documents without fallback do not require a layout proof or a match between the PDF page count and the layout proof. The document proof's QR digests describe intended payloads; this validator does not decode the emitted QR images and compare their bytes with those payloads.

   Sources: [validation.py:90](/Users/alstoyan/ethernity/src/ethernity/render/validation.py:90), [proofs.py:185](/Users/alstoyan/ethernity/src/ethernity/render/proofs.py:185), and the ordinary backup callers in [execution.py:333](/Users/alstoyan/ethernity/src/ethernity/workflows/backup/execution.py:333).

   I reproduced this without modifying painting code: setting `QrConfig(dark="white", light="white")` produced a main PDF whose proof reported four physical QR codes. No embedded QR image decoded, but `validate_rendered_pdf_document` accepted the result. The color fields are configurable and the loader does not require contrast between them.

   Three fault injection checks expose the same boundary. Removing the layout proof from an otherwise valid main result was accepted. Setting its document proof page count to 999 was accepted. Replacing the generated main PDF with a one page blank PDF, while retaining the original result, was also accepted. These checks demonstrate missing validation; they do not establish that the normal renderer spontaneously emits blank pages.

   Recovery documents have an additional content gap. The validator checks the extracted fallback frame data, but the backup caller supplies no expected passphrase or other required recovery metadata. I suppressed only the synthetic passphrase text during Sentinel painting. The resulting PDF retained valid fallback data, contained no printed passphrase, and still passed production validation. This was deliberate fault injection, demonstrating that omission of a required secret would escape the current check.

   Make the final artifact part of the contract: always validate layout and actual page counts; compare decoded QR payload bytes with the intended payloads; and validate required printed recovery metadata against `RecoveryMeta`, including values split across lines or continuation pages. Reject unusable QR color combinations before painting. Preserve the distinction between checking embedded QR images and checking their placement on composed pages; both are useful, but they prove different properties.

   This gap is not universal across all workflows. Extension publication already scans and validates staged main and head anchor carriers in [add_files/execution.py:344](/Users/alstoyan/ethernity/src/ethernity/workflows/add_files/execution.py:344). Those checks are a useful precedent for the ordinary backup path. They do not correct printed instructions or verify a recovery passphrase.

2. **P1: Valid threshold one shard documents make a false security claim.**

   Shard copy unconditionally says that possession of a single shard is insufficient for recovery. Header and footer guidance repeats that claim for root, replacement, and checkpoint shards. Threshold one is explicitly supported by the workflow and cryptographic implementation.

   Sources: [copy_catalog.py:89](/Users/alstoyan/ethernity/src/ethernity/render/copy_catalog.py:89), [copy_catalog.py:376](/Users/alstoyan/ethernity/src/ethernity/render/copy_catalog.py:376), and the allowed threshold in [backup_validation.py:65](/Users/alstoyan/ethernity/src/ethernity/workflows/shared/backup_validation.py:65).

   I generated an actual 1-of-2 passphrase shard set, recovered the original synthetic passphrase from the first shard alone, and rendered that shard in all five designs. Every PDF passed validation while claiming that the individual shard could not recover the secret. This can cause an owner or custodian to treat a complete recovery credential as though it provides only partial access.

   Derive security copy from the quorum. At threshold one, explicitly say that this document alone is sufficient to recover the secret. Apply the same rule to instructions, warning blocks, headers, footers, and signing key shard guidance. Keep threshold one supported unless a separate domain decision changes that policy. Add a regression test using a genuine threshold one shard, rather than only a synthetic frame labeled with quorum values.

3. **P2: A head anchor is rendered as an ordinary main document.**

   `render_head_anchor_document` passes the anchor JSON through `RenderService.qr_inputs`, which fixes the document type to main. It places `head_anchor` in the context dictionary, but no renderer consumes that field. The resulting copy describes ordinary document segments and recovery fallback rather than identifying the latest head record.

   Sources: [kit/service.py:225](/Users/alstoyan/ethernity/src/ethernity/workflows/kit/service.py:225), [render/service.py:108](/Users/alstoyan/ethernity/src/ethernity/render/service.py:108), and [copy_catalog.py:67](/Users/alstoyan/ethernity/src/ethernity/render/copy_catalog.py:67).

   I rendered real head anchor inputs with every design. All five sheets lacked a head anchor label and used main document guidance. The QR payload itself remained the correct anchor JSON. The defect concerns the printed role and handling instructions, not corruption of that payload.

   The publication specification treats the anchor as a separate external freshness record and latest recovery depends on the selected freshness basis: [extension_publication_rules.md:153](/Users/alstoyan/ethernity/docs/extension_publication_rules.md:153). A paper owner needs to recognize this sheet and know why its trusted storage matters.

   Give this artifact an explicit document role or typed content kind. Print its purpose, document identity, selected head information, and appropriate recovery kit and storage guidance. Avoid repairing the problem by inspecting an arbitrary context key inside each style. Add a test that asserts the printed role and instructions as well as the exact QR bytes.

4. **P2: SHRINK rejects text that fits at an allowed smaller size.**

   `TextBox.plan` computes the maximum line count using the initial font size. If even one initial line is too tall, it raises before invoking the shrink policy. The shrink loop has a second early exit: `_wrap_text` can raise when one character is wider than the box, and that exception prevents trying smaller sizes. The maximum line count also remains fixed while the font shrinks, although shorter lines would allow more lines vertically.

   Sources: [components.py:421](/Users/alstoyan/ethernity/src/ethernity/render/direct_pdf/components.py:421) and [text_fit.py:143](/Users/alstoyan/ethernity/src/ethernity/render/direct_pdf/text_fit.py:143).

   Using the real PDF surface and Helvetica, `hello` at 20 pt in a 50 by 7 mm box with a 6 pt minimum raises "text box height cannot fit one line". It fits at a permitted smaller size. Similarly, `W` at 12 pt in a 3 by 10 mm box raises for character width, although it fits at 6 pt.

   Evaluate width and height together for each candidate font size. Retry width failures while a smaller size remains available, and calculate line capacity from that candidate's line height. Fail only when the minimum permitted size cannot fit. Cover both reproductions and a case in which shrinking allows additional wrapped lines.

5. **P2: Text placement proofs do not bound the actual glyph ink.**

   Line placement treats the font size as the font's full height and positions the first baseline at the bottom of that height, plus half the leading. The reported used rectangle is derived from synthetic line height. Actual ascenders and descenders are not included in the contract. Descenders can therefore extend below the rectangle reported by the proof.

   Sources: [components.py:467](/Users/alstoyan/ethernity/src/ethernity/render/direct_pdf/components.py:467) and [components.py:528](/Users/alstoyan/ethernity/src/ethernity/render/direct_pdf/components.py:528).

   For the bundled Roboto Mono font at 12 pt, I planned `gypq` with a line height multiplier of one in a box starting at y=10 mm with a height of 5 mm. The proof's used rectangle ended at 14.233 mm. Computing the glyph bounds from the font outlines and planned baseline gives a bottom at 15.137 mm, beyond even the assigned box's bottom at 15 mm.

   I also instrumented ordinary Sentinel rendering on A4 and Letter. Several recovery and shard text components had calculated glyph bounds extending roughly 0.06 to 0.24 mm below their assigned boxes. These were small escapes; visual inspection did not reveal gross clipping. They still establish that a clean geometry proof does not currently guarantee containment of the text it describes.

   Expose font metrics through the surface abstraction and use ascent and descent to position baselines and report conservative ink bounds. Treat line spacing separately from ink bounds. Verify both outlined glyph bounds and rendered pages after changing this shared primitive, and update visual baselines only for the resulting intentional changes.

6. **P2: The central QR QA gate checks quantity rather than payload identity.**

   The visual baseline script compares the number of decoded embedded and composed QR codes with `physical_qr_count`. It never compares their payload bytes with the expected payloads. The same count can contain wrong, duplicated, or substituted symbols. Its main document samples also contain approximately 30 bytes of frame data, while normal backup chunks are substantially larger; kit examples use small synthetic payloads rather than realistic HTML chunks.

   Sources: [render_visual_baselines.py:473](/Users/alstoyan/ethernity/scripts/render_visual_baselines.py:473), [render_visual_baselines.py:850](/Users/alstoyan/ethernity/scripts/render_visual_baselines.py:850), and [render_visual_baselines.py:930](/Users/alstoyan/ethernity/scripts/render_visual_baselines.py:930). The shipped backup configuration uses 512 byte chunks; kit construction starts from a 1200 byte limit subject to capacity checks.

   Some individual style tests already check exact QR payloads. The finding concerns the shared design and paper matrix, where payload identity should be a central invariant. Extend that gate to compare expected bytes and multiplicity, and verify ordering where the document protocol requires it. Include realistic dense payloads, near capacity cases, and both raw and base64 encoding. Add negative cases for missing or substituted output rather than relying only on successful renders.

   My additional density check passed: five designs, two paper sizes, two encodings, and twelve 1024 byte frame payloads per case. All 240 QR codes decoded from whole pages rasterized at 200 DPI and matched the expected payload bytes. This is evidence that the current layouts handle that density; the recommendation is to preserve that assurance in the regular QA matrix.

7. **P3: The character spacing interface uses the wrong units.**

   `TextStyle.char_spacing_mm` is passed directly to FPDF's character spacing setting, whose emitted PDF value is in points. One configured unit therefore produces approximately 0.3528 mm of spacing rather than 1 mm. Measurements and painting share the same mismatch, so internal proof agreement does not reveal it.

   Source: [surface.py:251](/Users/alstoyan/ethernity/src/ethernity/render/direct_pdf/surface.py:251).

   I confirmed the behavior against the installed implementation and with the real surface's width measurements. A ten character string with `char_spacing_mm=1` gained 3.528 mm of measured width, consistent with one point per character rather than one millimeter. Convert millimeters to points at the surface boundary, or rename the field to points and deliberately migrate the existing style constants if their visual intent was point based. Verify affected typography before updating baselines.

**The implementation is clean at its outer boundaries and less consistent inside the style backends.**

The engine has several design decisions I would preserve. `RenderInputs` carries an explicit document type and lineage, recovery rendering consumes structured `RecoveryMeta`, and drawing is mostly isolated behind `PdfSurface` and reusable component plans. Geometry and pagination reject impossible capacities rather than silently looping. Shared shard checks tie the QR and fallback representation to the same frame. Extracted fallback validation checks decoded frame bytes, labels, ordering, and extra content, which is substantially stronger than checking that text or pages merely exist. Default main and recovery pages looked coherent in all five designs on both paper sizes.

The principal maintenance concern is duplicated policy and orchestration. Roughly 28,000 lines in the rendering package are not inherently excessive for five detailed designs; much of that code is declarative drawing. However, Ledger and Maritime contain near identical instruction layout functions. Their 165 line instruction insert builders are approximately 99.7 percent similar after AST normalization, and related callout, footer, and kit instruction builders are also nearly identical. Compare [ledger.py:1623](/Users/alstoyan/ethernity/src/ethernity/render/direct_pdf/ledger.py:1623) with [maritime.py:1673](/Users/alstoyan/ethernity/src/ethernity/render/direct_pdf/maritime.py:1673).

Extract those shared structures with explicit palette and typography inputs. Keep genuine design geometry local. The same principle applies to the separate render lifecycles: common preparation, planning, painting, proof collection, and finalization deserve a shared runner with typed plans. Design modules should primarily decide composition and appearance. The existing classic planner and structured rendering helpers provide starting points; a wholesale rewrite would discard useful working code.

Sentinel's responsiveness is also harder to reason about than it should be. It remaps already measured reference plans, treats plan types differently, reconstructs text proofs, and uses substrings such as `qr-frame` to decide geometry behavior: [sentinel/shell.py:611](/Users/alstoyan/ethernity/src/ethernity/render/direct_pdf/sentinel/shell.py:611). Current A4 and Letter probes passed, so this is a maintenance assessment rather than an additional demonstrated rendering failure. Prefer explicit layout attributes and measurement against the final target rectangles. This would make future paper sizes and component changes less dependent on identifier conventions.

There is a smaller abandoned contract: the UI exposes "Render jobs", and `RenderInputs` receives `render_jobs`, but no rendering backend uses it. The relevant paths are [settings.py:332](/Users/alstoyan/ethernity/src/ethernity/tasks/settings.py:332), [render/service.py:276](/Users/alstoyan/ethernity/src/ethernity/render/service.py:276), and [render/types.py:75](/Users/alstoyan/ethernity/src/ethernity/render/types.py:75). Remove or deprecate that setting unless an actual execution policy will consume it.

**Verification completed during this audit gives substantial confidence in the working paths.**

- Ruff lint passed for the rendering package and visual baseline script.
- Ruff formatting passed for the same scope.
- `uv run pyrefly check` completed with zero errors.
- 373 rendering focused tests passed, including shared components, design backends, dispatch, proofs, copy, fallback, document metadata, page geometry, and visual baseline tests.
- 22 selected backup, recovery, extension, and kit tests passed.
- Five selected CLI and sharding end to end tests passed.
- The additional 20 case density matrix decoded all 240 expected QR payloads from composed pages with exact byte matches.
- I visually inspected main and recovery first pages for every design on A4 and Letter, and separately checked threshold one shards and head anchors.

The total was 400 passing selected tests. This was not a run of the entire repository suite, a release packaging build, or a physical print and camera trial. Fault injection and the reproduced edge cases show why passing existing tests does not resolve the findings above.

I would address the work in this order: strengthen validation of actual required output and correct threshold one security copy; introduce proper head anchor semantics; repair text fitting, font bounds, and spacing units; then consolidate duplicate render lifecycles and layout structures. Add the regression checks alongside those fixes so the improved contracts remain enforced. The engine's foundation supports this work without a replacement architecture.
