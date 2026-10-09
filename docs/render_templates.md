# PDF templates

All five designs use the same rendering engine. Their artwork lives in `style.json`;
`design.json` declares supported document types and minimum paper dimensions. Neither file
contains Python, and adding a design requires no registration table.

The existing designs are part of the product. Refactoring the renderer must preserve their
appearance: typography, colors, borders, instruction panels, QR arrangements, and continuation
pages. Changes to those designs need a separate, deliberate decision.

## Add or edit a design

Copy a directory under `src/ethernity/resources/designs/`, change the name in both JSON files,
and edit the template. The renderer discovers built-in directories automatically. It also
accepts an external directory as `RenderInputs.design_name`.

A template has three parts:

- `styles`: fonts named for their use, such as `document-title`, `metadata-label`, and
  `fallback-body`, with size, weight, color, and optional character spacing.
- `components`: reusable artwork, such as a header, QR card, or instruction panel.
- `documents`: first-page and continuation layouts for each supported document type.

A design can list JSON files in `component_sources`, each containing a `components` map.
The loader looks in the design directory first, then `resources/designs/_shared/`. Local
components override imported ones; later imports override earlier imports. Imports contain artwork only, with no nested imports;
the complete template still validates all component and style references before rendering.
Archive, Ledger, and Maritime share A5 guide sections through `kit-guide.json`. Ledger and
Maritime also share the original full-size text layout through `kit-guide-wide.json`. The
full-size designs retain their original frames, icons, cards, checklists, and text positions.
Their own styles supply the typography and colors. Instruction wording lives in
`copy_catalog.py`, including the shorter lines that fit the original layouts.

Elements have a stable key, a kind, and a rectangle `[x, y, width, height]`. Coordinates are
millimeters on the template's `reference_size`, which defaults to `[210, 297]` for A4. The engine
adapts placement to the requested paper size while measuring text with the actual font metrics
and keeping QR images square. Font sizes are physical points, not scaled page coordinates.

For example, this component prints a title using values supplied by the engine:

```json
{
  "key": "title",
  "kind": "text",
  "box": [15, 15, 180, 12],
  "text": "{copy_title}",
  "style": "heading",
  "fit": "wrap"
}
```

Text, panels, rules, lines, ellipses, and QR images are shared primitives. A `group` references
a named component and supplies its position. `repeat` and `step` describe regular decoration,
such as dashed lines. QR slots associate card artwork with payloads; the shared grid handles
partial rows and reading order.

Archive, Ledger, and Maritime each share QR cards and grids between backup and kit pages.
A4 and Letter use three columns and four rows, including the first page. Partial pages fill
from the top left without moving the remaining codes. Backup and recovery instructions appear
only on the first QR or fallback page. Kit QR pages share one layout without an instruction
card; full kit instructions appear on the final page.

Within each design, recovery documents and both shard types share fallback cards, headings,
and numbered rows across sizes. A5 uses measured cards for recovery keys and an upper-right
identity card. Shards show their number there, with the page number in the footer. Both shard
types reference the same document layout and receive their own instructions through bindings.
Kits omit backup identifiers and metadata cards. Each design shares its footer across all
document types and sizes.

Instruction cards reuse the design's typography and insets. Full-size recovery and shard
pages share a card; the shorter main card leaves room for four QR rows. A5 main and recovery
pages share a full-width card, while shard instructions fit beside their QR code.
`instructions_text` supplies brief scanning copy where available, otherwise the document's
full instruction lines. The individual `instruction_N` bindings remain available for step lists.

Define a shared section once in `components`, then reference it from each page that needs it:

```json
{"key": "footer", "kind": "group", "ref": "footer", "box": [0, 0, 0, 0]}
```

Group coordinates offset every child, including nested groups. Keep reusable instructions and
decorations relative to their group so they can appear at different positions. A repeated row
inside a repeated group can describe a dot grid without listing every dot. Keep unique artwork
in its page component; share sections with the same appearance and purpose.
When a group declares a nonzero width, children with `stretch_x` extend to its right edge.
Archive uses this for one footer component across paper sizes; only its placement and width change.
Likewise, `stretch_y` extends a decoration to its group's declared height. Give the outer
placement group zero width and height when its nested groups already define their own sizes.

Omit settings that equal the defaults in `template.py`, such as left alignment, normal font
weight, and zero character spacing. Omit `continuation` when it is identical to `first`.
Use descriptive component names and remove floating-point arithmetic noise from coordinates.
Check any coordinate changes against the original-design fixtures.

For text that follows a variable-length heading, `after` names an earlier element in the same
component and `gap_after` sets the minimum gap in millimeters. The original position is retained
when the heading fits. `max_lines` keeps encoded payload rows on one line; `scale_height` lets
instruction boxes fit within their allotted space on smaller paper.

Document layouts declare the content areas they need. Recovery documents have measured metadata
fields and fallback profiles, including a separate passphrase continuation page. Recovery sheets
have readable density profiles for fitting their payload on one page. Inventory tables measure
each row and paginate without truncating descriptions. Templates choose appearance; the engine
owns encoding, content measurement, pagination, and payload accounting.
For sheets, `qr_area_top` centers the complete QR group between that template coordinate and
the measured fallback card. QR frames and corner marks belong in the same `qr_slot` group.
The renderer rejects a group that cannot fit in the available space.
For an unframed QR beside sheet instructions, `qr_bottom_gap` lets the image shrink only when
the measured fallback card needs more room. Ordinary payloads retain the template's full QR size.
Fallback line numbers continue within each frame across page breaks and restart for a new
frame. Number gutters account for three or more digits without losing encoded data.
`number_maximum_width` caps a recovery profile's number gutter when its number element uses
`fit: "shrink"`. Keep its minimum font size readable and verify the maximum line count fits.
Recovery `section_gap_rows` reserves blank rows between frame cards on the same page.
The gap is included in pagination and is omitted at the start of a page.
A sheet density can set `title_height` when its heading font needs more height than the
payload rows. The shared fitter reserves that space in the card and moves subsequent rows;
payload font size and line spacing stay unchanged.

`src/ethernity/render/template.py` defines the settings. Unknown fields, invalid colors,
non-finite dimensions, missing styles, and cyclic component references are rejected before
rendering. Text fitting is explicit: `fail`, `wrap`, or `shrink`, with a readable minimum size.
Impossible page layouts raise an error.

Use named bindings for variable content. Never paste sample IDs, recovery phrases, payloads,
quorum values, or page counts into artwork. Document behavior comes from typed
`RenderInputs.doc_type`, `origin`, and `recovery_meta`, not displayed text.

## Compact paper layouts

A5 is available throughout the app and commands through the paper-size registry. All five
built-in designs use `resources/designs/_shared/compact.json` for smaller pages. Its reference
size is `[148, 210]`. Each design supplies fonts, colors, and decoration through a
`compact_layout` entry in `style.json`. A4 and Letter retain their existing composition.

For example, an external design can select a local compact template with:

```json
"compact_layout": {
  "source": "small.json",
  "below_width_mm": 200,
  "below_height_mm": 279.4,
  "styles": {
    "compact-title": {"source": "document-title", "size_pt": 18},
    "compact-body": {"source": "body", "size_pt": 8.5}
  }
}
```

The engine selects this layout if either physical dimension is below its threshold, including
custom paper sizes. `design.json` still defines the minimum supported dimensions. `source`
names a JSON file in the design directory, falling back to the packaged `_shared` directory.
Each style entry inherits a font and color from the base template and clears character spacing;
`size_pt` is optional. Components inherit from the base design, then the compact source, then
the design's compact overrides. Optional `documents` replace named entries in the compact
source. Components retain the usual group references. This needs no new Python builder.

Fallback section components receive their measured height. Set `stretch_x` on a section panel
to fill the profile's width; the same card can then serve full-size and compact pages.
Sheet decorations, titles, and rows also accept component references. They expand before
measurement, including column fitting. A sheet decoration with `stretch_x` and `stretch_y`
fills the measured fallback area. Archive shares its card, title, and numbered row between
recovery documents and both kinds of shard on every paper size.
Separate number columns grow to fit the displayed line number. The payload text and its
enclosing panel give up the same width, matching the paginator's measurement.

The compact layout uses fewer QR codes per page, a single fallback column, and measured metadata
stacks. Ordinary recovery sheets start at 8pt fallback text; unusually large sheet payloads can
use the existing 6pt floor to keep one QR and its complete fallback on one sheet. Separate number
labels remain at least 6.5pt; inline numbers use the payload font. Passphrases and recovery-document
fallback continue onto extra pages without dropping content. Set metadata `repeat_on_continuation`
to `false` when later fallback
pages should use the full content area. Keep passphrase pagination and text-box line heights equal.

Document types that share composition can use a reference such as
`"signing_key_shard": {"use": "shard"}`. The engine still supplies each document's own typed
content and instructions. Missing and cyclic references fail validation.

## Code ownership

- `engine.py` validates inputs and dispatches the shared document compositions.
- `artwork.py` resolves bindings and paints declared components.
- `artwork_metadata.py`, `artwork_recovery.py`, `artwork_sheet.py`, and
  `artwork_inventory.py` measure their respective content regions.
- `document_inputs.py` builds metadata, document copy, and QR payloads.
- `fallback_layout.py` paginates fallback data using measured font widths and gutters.
- `recovery_metadata.py` splits long passphrases losslessly.
- `components.py`, `page.py`, and `surface.py` measure and paint PDF primitives.

Add new layout behavior to these shared components with a typed setting and tests. Do not add
per-design builders, branches on design names, or another renderer alongside this one.

## Verify a change

Run the template and output contracts:

```sh
uv run pytest tests/unit/test_design_style.py tests/rendering/test_template_engine.py tests/rendering/test_render_output_validation.py
```

These cover all built-in document types, supported page geometries, maximum-size sheets, long
passphrases, new templates without registration, and multi-page fallback payloads. Output checks
decode the composed QR images and extracted fallback text and compare them with the inputs.

The original-design regression fixtures compare rendered pages with the previous renderer,
including QR continuations and instruction inserts. Deliberate visual revisions have separate
references under `tests/fixtures/render/revised-designs`, with the reason in its manifest.
Those cases replace the original comparison; the historical images remain intact. Do not add
revisions merely because a refactor changes the output. Use `scripts/render_visual_baselines.py`
for PDFs, raster
previews, layout reports, and scan checks. `RenderInputs.layout_debug_json_path` adds diagnostics
without changing the document.

All built-in template fonts are embedded as subsets. Helvetica, Courier, and Times resolve to
the bundled Nimbus Sans, Nimbus Mono PS, and Nimbus Roman faces, with their original template
line boxes retained. Font files, license texts, and the pinned upstream source are under
`resources/designs/_shared/assets/fonts`. This avoids viewer-dependent font substitution and
allows the same visual references to run on macOS, Linux, and Windows.

```sh
uv run pytest tests/rendering/test_original_render_designs.py
```

Keep older backup-format fixtures and recovery tests intact. A renderer refactor is not a reason
to regenerate compatibility fixtures.
