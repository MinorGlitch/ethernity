# Original PDF designs

These A4 pages were rendered using the Python design builders from commit `868a87be`,
before their replacement by the shared template engine. They were recovered from Git and
rendered in isolation, using the deterministic inputs in `scripts/render_visual_baselines.py`.

The fixtures cover all 27 supported design/document combinations and every page in each example,
including QR continuations, recovery fallback continuations, and kit instruction inserts.
The PDFium raster scale is 1.2, recorded in `manifest.json`.

`tests/unit/test_original_render_designs.py` compares the shared engine against these references.
They protect the original appearance; do not regenerate them from the new renderer to make a
refactor pass. Format compatibility fixtures are separate and remain unchanged.
