# Rendering Reimplementation Plan

## Objective

Reimplement Ethernity PDF rendering without an external browser renderer while preserving the
current visual identity, layout intent, hierarchy, and tone of the supported render styles:
`archive`, `forge`, `ledger`, `maritime`, and `sentinel`. This is not a redesign of the visual styles.
The new renderer must make clipped text a layout failure, not a possible output artifact.

## Architecture Direction

Use a direct PDF renderer with one engine responsible for measurement, pagination, and painting.
Keep the public render contract stable during migration by routing existing callers through
`render_frames_to_pdf(inputs)` while the implementation gains a backend boundary.

The target pipeline is:

```text
RenderInputs
  -> DocumentContent
  -> DesignTheme
  -> Component tree
  -> Measured PagePlan
  -> Overflow validation
  -> PDF paint
  -> RenderResult + render proof
```

HTML/Jinja templates are visual references during migration, not the final rendering mechanism.

The first backend candidate is `fpdf2`, because it provides page sizing, drawing primitives,
TrueType font embedding, image embedding, and PDF output without launching an external browser.
Its role should stay behind the PDF surface adapter rather than leaking into layout code. Reference:
[`fpdf2` documentation](https://py-pdf.github.io/fpdf2/index.html).

## Code Quality Rules

- Follow the repository's Ruff configuration and local AGENTS conventions: top-level imports,
  explicit public exports, small helpers, and Python line length of 100.
- Follow Python's readability-first guidance from [PEP 8](https://peps.python.org/pep-0008/).
- Use concise docstrings for public modules, classes, and non-obvious functions, guided by
  [PEP 257](https://peps.python.org/pep-0257/).
- Prefer frozen dataclasses for immutable layout values, using the standard
  [`dataclasses`](https://docs.python.org/3/library/dataclasses.html) module.
- Use `Protocol` boundaries for renderer adapters and component contracts where structural typing
  keeps the code decoupled, following the Python typing
  [protocol specification](https://typing.python.org/en/latest/spec/protocol.html).
- Do not build a broad DSL first. Start with typed Python components and small theme objects.
- Keep backend-specific calls behind a thin surface adapter so the layout engine is not coupled
  directly to raw `fpdf2` calls.

## Non-Negotiable Invariants

- Every text component must choose one explicit fit policy: wrap, shrink within configured limits,
  split across pages, or fail.
- No renderer may silently clip text, QR images, fallback blocks, metadata, or page furniture.
- Render proofs must include enough geometry to validate fit decisions and page placement.
- QR scan semantics, fallback recovery text, recovery metadata, lineage, and kit index behavior
  must remain compatible.
- Preserve each existing render style's visual language and document structure. Exact pixel
  matching is not required, but intentional design changes are out of scope.
- A direct renderer is not accepted merely because it is browser-free and semantically valid. It
  must read as the same design family as the current template: typography, visual density, section
  hierarchy, borders, warning treatments, QR framing, metadata treatments, and footer/header
  behavior must be carried over unless an intentional deviation is documented.
- Fix legacy rendering bugs that violate design intent, such as clipped text, overflow, illegible
  shrinkage, or accidental spacing collisions. Do not reproduce those bugs merely to match a
  screenshot.
- Direct PDF is the primary renderer once every supported PDF path has a direct-render
  replacement.

## Migration Slices

- [x] **S01: Direct PDF Feasibility Spike** `risk:high` `depends:[]`
  > After this: `fpdf2` is proven viable for fonts, QR images, borders, metadata, and one dense
  > Forge-style page; otherwise the same architecture switches to ReportLab.

- [x] **S02: Render Backend Boundary** `risk:medium` `depends:[S01]`
  > After this: existing callers still call `render_frames_to_pdf(inputs)`, but the renderer can
  > dispatch through an explicit backend boundary.

- [x] **S03: Visual Baseline Harness** `risk:medium` `depends:[]`
  > After this: current template PDFs/PNGs exist as visual baselines for every supported
  > design/document pair.

- [x] **S04: Font And Asset Registry** `risk:high` `depends:[S01]`
  > After this: rendering uses explicit font roles and packaged asset registration. Bundle assets
  > when the current templates package them or name open fonts that should be stable across
  > systems; otherwise document the effective rendered fallback family so the direct backend
  > preserves today's visual output.

- [x] **S05: PDF Surface Adapter** `risk:medium` `depends:[S04]`
  > After this: layout components measure and paint through a small direct-PDF surface API.

- [x] **S06: Measured Component Primitives** `risk:high` `depends:[S05]`
  > After this: shared primitives such as `TextBox`, `MonoBlock`, `Rule`, `Panel`, `LabelPill`,
  > `MetadataStrip`, `QrGrid`, `FallbackBlock`, and `PageShell` can measure before painting.

- [x] **S07: Overflow Proof Model** `risk:high` `depends:[S06]`
  > After this: render results report placed bounding boxes, fit decisions, overflow status,
  > split decisions, and per-page component inventory.

- [x] **S08: Forge Recovery Vertical Slice** `risk:high` `depends:[S03,S06,S07]`
  > After this: Forge recovery document renders through direct PDF, matches the current Forge
  > visual language, and passes proof plus QR/fallback validation.

- [x] **S09: Forge Theme Contract And Style Parity Gate** `risk:high` `depends:[S08]`
  > After this: Forge has explicit theme/layout components for its real style, and every Forge
  > direct document is reviewed against current template rasters before it can be called accepted.
  > This is not pixel-perfect matching, but "same design family" is mandatory.

- [x] **S10: Forge Remaining Documents** `risk:medium` `depends:[S09]`
  > After this: Forge main, shard, signing-key shard, kit, and kit index documents each have their
  > own direct-PDF layout where needed, are browser-free, and pass the Forge style parity gate.

- [x] **S11: Sentinel Migration** `risk:medium` `depends:[S10]`
  > After this: a second visually distinct design proves the component model is not Forge-specific.

- [x] **S12: Archive, Ledger, Maritime Migration** `risk:medium` `depends:[S11]`
  > After this: all core backup/recovery design families render directly.

- [x] **S13: Envelope PDF Replacement** `risk:low` `depends:[S05]`
  > After this: envelope PDF rendering uses the direct PDF backend.

- [x] **S14: Default Backend Flip** `risk:medium` `depends:[S12,S13]`
  > After this: direct PDF is the default backend.

- [x] **S15: Browser Dependency Removal** `risk:medium` `depends:[S14]`
  > After this: runtime dependencies, startup checks, cache paths, packaging resources, scripts,
  > tests, and setup docs no longer require an external browser.

- [x] **S16: Golden And E2E Refresh** `risk:medium` `depends:[S15]`
  > After this: regenerated golden fixtures and E2E tests verify direct-rendered PDFs through QR
  > scanning, fallback recovery, page counts, and render proofs.

## Current Progress

- [x] Created `src/ethernity/render/direct_pdf/` with a small `PdfSurface` protocol, an `fpdf2`
  adapter, immutable geometry/color/text types, packaged font registration, measured text fitting,
  component plans, page proof aggregation, and a Forge visual preview.
- [x] Added a `RenderInputs`-driven Forge recovery direct renderer that reuses existing recovery
  copy, fallback encoding, metadata, doc-type, lineage, and render proof contracts.
- [x] Added focused unit coverage for measurement, assets, components, page proofs, Forge preview,
  Forge recovery PDF output, fallback proof validation, PDF text extraction, and multipage fallback
  pagination.
- [x] Wired the direct renderer behind `render_frames_to_pdf(inputs)` and later collapsed that
  boundary to direct-only registry dispatch. Supported renders route by design `style.json` name
  and explicit `doc_type`; unsupported design/document/input shapes fail explicitly.
- [x] Added direct Forge main-document rendering with measured QR card placement, multipage QR
  pagination, physical QR payload indexes, PDF output, and extractable segment labels.
- [x] Added direct Forge shard rendering with measured QR placement, fallback text pagination,
  repeated QR thumbnails on continuation pages, physical QR proof indexes, and fallback proof
  validation.
- [x] Added a dedicated direct Forge signing-key shard renderer instead of reusing the regular
  shard layout. It preserves the template's dashed warning panel, blueprint key-material zone,
  public reference block, specifications table, QR repeat behavior, and fallback proof contract.
- [x] Added direct Forge kit and kit-index rendering with measured QR chunk pagination,
  instruction/inventory pages, artifact proof coverage, dispatch tests, and extractable PDF text.
- [x] Added `scripts/render_visual_baselines.py`, a typed developer harness that discovers the
  supported design/document matrix, renders stable synthetic fixtures through the direct renderer,
  optionally rasterizes pages with `pdftoppm`, writes a JSON manifest, and supports pairwise
  image-delta diagnostics for manual visual review.
- [x] Verified the harness can render all current direct Forge document types without a browser
  by running it with `--design forge --rasterize never`.
- [x] Generated a local Forge raster diagnostic manifest with
  `scripts/render_visual_baselines.py --design forge --rasterize auto`; the harness
  now normalizes one-pixel raster-size drift and reports image delta metrics as review evidence,
  not pass/fail pixel-perfect gates.
- [x] Updated direct Forge recovery pagination to honor the Forge
  `recovery_first_page_single_section` style capability, matching the intended two-page AUTH/MAIN
  section split for the synthetic fixture.
- [x] Extended the visual harness to emit per-page PNG diff images and named header/body/footer region
  deltas. The current Forge manifest shows recovery and kit-index mismatches are header-heavy,
  while main, shard, and kit page 1 are body-heavy.
- [x] Added shared direct-PDF page-plan bounds validation so component rectangles and measured text
  used rectangles must stay inside their assigned page/box before a page can be painted.
- [x] Added direct-PDF layout debug JSON sidecars from measured page plans, preserving the existing
  `RenderInputs.layout_debug_json_path` diagnostics contract without going through a browser.
- [x] Refactored Forge recovery onto the shared Forge shell context/header/footer helpers so the
  design chrome is preserved through one implementation instead of duplicated recovery-specific
  plumbing.
- [x] Added renderer-neutral layout proof dataclasses and direct-PDF proof conversion so direct
  Forge render results expose measured page/component geometry, overflow status, and text used
  rectangles without relying on optional debug sidecars.
- [x] Tuned the direct Forge main visual slice after raster review: removed invented header chrome
  from main pages, restored the template's directive-card icon treatment, fixed the directive title
  and card collision, and restored the width-driven QR card scale/spacing used by the current
  template.
- [x] Reworked the shared Forge header to measure title wrapping before placing subtitle,
  guidance, and the header rule, matching wrapped Forge titles such as recovery and kit-index
  documents instead of shrinking them onto one line.
- [x] Removed the invented Forge recovery fallback outer frame and shortened recovery fallback line
  grouping so the direct renderer follows the current template's unframed two-column row rhythm.
- [x] Tuned Forge shard fallback line grouping toward the current template's compact manual
  transcription density while keeping the user's requested omission of the decorative diagonal
  watermark as an intentional visual deviation.
- [x] Restored the Forge shard signature strip to the current template's dashed verification
  treatment and signature/date blanks while preserving the intentional no-watermark deviation.
- [x] Added an explicit Forge theme contract that records CSS reference families separately from
  the effective direct-PDF families. Current Forge HTML packages only Material Symbols, so the
  direct renderer intentionally preserves the rendered Times/Helvetica/Courier text fallback
  style instead of introducing new bundled text fonts and changing the design.
- [x] Extended the shared asset registry with bundled Public Sans and Roboto Mono font assets for
  Sentinel direct rendering. Sentinel templates explicitly name these families, and bundling them
  keeps the direct renderer browser-free while avoiding host/system font drift.
- [x] Tuned Forge main and recovery style parity after visual review: main titles now keep the
  current one-line header treatment, directive cards wrap instead of shrinking long copy, recovery
  body text uses template-scale sizing, and recovery metadata returned to stacked full-width boxes.
- [x] Tuned Forge kit QR page style parity after visual review: restored the current template's
  offline-processing classification badge, blue warning strip/icon treatment, early content start,
  and larger QR cards/images.
- [x] Tuned Forge kit instruction-page style parity after visual review: restored the current
  template's bordered instruction shell, icon label badges, large scan/checklist treatments,
  right-column verification/storage/security cards, checklist card, and split footer.
- [x] Tuned Forge kit-index style parity after visual review: restored the template-scale stats,
  blue warning treatment, inventory/custody icons, denser inventory table, custody cards, and
  protocol/signature footer block.
- [x] Removed the false signing-key shard route through the regular shard renderer after visual
  review showed it was the wrong layout family, then restored direct support through the dedicated
  renderer.
- [x] Started Sentinel migration with a direct recovery vertical slice. Sentinel now has its own
  theme and shell helpers rather than reusing Forge chrome, plus measured warning/session-log,
  manual transcription, metadata, continuation, fallback proof, backend dispatch, and visual
  harness support for `sentinel/recovery`.
- [x] Added direct Sentinel main-document rendering with its own QR layout: directive rail,
  filled numbered markers, security notice, primary QR frame, secondary segment cards,
  continuation QR grid, render proof, dispatch, and visual harness support for `sentinel/main`.
- [x] Added direct Sentinel shard rendering with the template's warning panel, shard heading,
  orange QR corner marks, patterned manual-transcription panel, repeated QR behavior for
  continuation pages, fallback proof, artifact proof, backend dispatch, and visual harness support
  for `sentinel/shard`.
- [x] Added direct Sentinel signing-key shard rendering with the dashed security panel, QR/text
  key-material layout, master-fingerprint and schema cards, continuation QR repeat behavior,
  fallback proof, artifact proof, backend dispatch, and visual harness support for
  `sentinel/signing_key_shard`. The decorative rotated "Restricted Access" watermark remains an
  intentional omission for now, consistent with the no-watermark direction already taken for Forge
  shard output.
- [x] Added direct Sentinel kit-index rendering with the template's custody-log shell, stats band,
  warning panel, hardware inventory table, chain-of-custody table, artifact proof, backend
  dispatch, and visual harness support for `sentinel/kit_index`.
- [x] Added direct Sentinel recovery-kit rendering with the template's orange media strip,
  QR-card page, dotted Sentinel background treatment, full-page instruction sheet, artifact proof,
  backend dispatch, and visual harness support for `sentinel/kit`.
- [x] Generated a Forge + Sentinel diagnostic manifest at
  `/tmp/ethernity-direct-migration-pass-17/manifest.json`; the visual harness now reports direct
  support for all 12 currently discovered Forge/Sentinel design-document cases.
- [x] Added direct Archive rendering for main, recovery, shard, signing-key shard, and recovery-kit
  documents. Archive uses a dedicated shell/context and measured direct-PDF layouts for its
  black-rule/blue-accent operational style, with QR pagination, fallback proof validation, kit
  instruction pages, backend dispatch, and visual harness support.
- [x] Extracted shared structured-document direct rendering mechanics into
  `src/ethernity/render/direct_pdf/structured_common.py` so Archive, Ledger, and Maritime share
  QR payload resolution, fallback encoding/pagination, artifact proofs, fallback proofs, render
  dispatch, layout sidecars, timestamps, and document context without copying those mechanics.
- [x] Added direct Ledger rendering for main, recovery, shard, signing-key shard, and recovery-kit
  documents. Ledger preserves the cream paper, boxed metadata rail, divider treatment, QR cards,
  left-accent fallback blocks, and instruction insert while fixing a fallback-block overlap found
  during raster review.
- [x] Added direct Maritime rendering for main, recovery, shard, signing-key shard, and recovery-kit
  documents. Maritime preserves the nautical stamp header, pale blue paper, outlined QR field,
  surface fallback blocks, and instruction insert while sizing QR fields to occupied rows instead
  of forcing unnecessary blank grid height.
- [x] Generated Ledger and Maritime diagnostic manifests at
  `/tmp/ethernity-ledger-pass-3/manifest.json` and
  `/tmp/ethernity-maritime-pass-2/manifest.json`; both report direct support for every discovered
  document template in those design families.
- [x] Generated a fresh all-design visual manifest at
  `/tmp/ethernity-direct-migration-all-pass-3/manifest.json`; direct support now covers all 27
  discovered design-document cases in the synthetic visual fixtures.
- [x] Replaced envelope PDFs with a direct renderer that preserves page sizes, the 7 mm rounded
  frame, centered logo placement, and default-logo visual geometry while scaling pathological custom
  logos to avoid clipping.
- [x] Made direct PDF the default backend and removed the external browser runtime dependency,
  startup installer, browser cache path, package metadata, bundle script references, and obsolete
  browser-render tests.
- [x] Removed the remaining backend selection compatibility surface. `render_frames_to_pdf(inputs)`
  now calls the direct-PDF registry without an environment-variable selector or legacy fallback path.
- [x] Generated a final all-design direct manifest at
  `/tmp/ethernity-direct-migration-final-check/manifest.json`; it covers all 27 discovered
  design-document cases with no unsupported direct renders.
- [x] Used the all-design manifest as the acceptance review index for Forge, Sentinel, Archive,
  Ledger, and Maritime. The review should focus on hierarchy, spacing, footer/header treatment, QR
  framing, metadata treatment, and documented bug-fix deviations, not pixel-perfect raster
  matching.
- [x] Refreshed golden/E2E coverage for the direct renderer by preserving logical shard projection
  assertions across repeated physical QR copies, updating direct layout-debug sidecar compatibility
  fields, and verifying `tests/integration tests/e2e`.

## Proof Strategy

- Unit-test measurement and fitting for each primitive.
- Property-test long titles, doc IDs, passphrases, shard labels, fallback lines, and metadata.
- Validate every direct-rendered PDF with existing page, QR, and fallback proof checks.
- Add overflow proof checks before visual review checks.
- Use rasterized output against current visual references as diagnostics for reviewing drift in
  design language, hierarchy, spacing, and density. Raster deltas are not a pixel-perfect
  acceptance gate.
- Document intentional deviations when the direct renderer fixes an existing rendering bug rather than
  reproducing it.
- Keep semantic tests stricter than visual tests: scan/recover behavior must remain exact.

## Follow-On Design Contract Migration

The packaged `*.html.j2` files have been removed. Built-in render styles are now code-only PDF
renderers backed by explicit per-style manifests:

- Each supported style directory contains `design.json` and `style.json`.
- `RenderInputs.design_name` plus mandatory `RenderInputs.doc_type` identifies the renderer and
  document contract.
- User config keeps one convenience default at `[render] style = "sentinel"`; users no longer point
  at template files or manage copied template folders.
- Recovery-kit index support is declared by manifest document support plus the
  `recovery_kit_index_document` style capability.
- Visual baseline discovery enumerates manifest-backed design/document cases.

Completed migration checklist:

1. Added per-design manifests for `archive`, `forge`, `ledger`, `maritime`, and `sentinel`.
2. Replaced config defaults and render inputs with `design_name` plus `doc_type`.
3. Removed user template sync, copied-template overrides, and legacy render path routing.
4. Moved kit-index compatibility discovery to design/style capabilities.
5. Updated direct-render, layout, proof, config, API, and visual-baseline tests.
6. Deleted unused HTML document templates, Jinja partials, Tailwind browser-template assets, and
   Jinja-only tests.

## Definition Of Done

- No external browser renderer package is a project dependency.
- Startup no longer installs or checks Chromium.
- Backup, extend, mint, compact, kit index, shard, recovery, and envelope PDF paths render directly.
- Every render result proves there was no overflow.
- Generated PDFs scan and recover successfully in existing E2E flows.
- Current visual styles and layout intent are preserved, with any intentional bug-fix deviations
  documented.
- Documentation and repository rules describe the new renderer contract.
