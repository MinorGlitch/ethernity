# AGENTS.md

## Purpose

This repository contains a Python CLI and a browser-based recovery kit. This file defines stable
conventions and a glob-based, working-tree inventory contract for contributors and coding agents.

## Scope and Baseline

- Baseline: the current working tree (including uncommitted and untracked files).
- Inventory scope: `src/`, `kit/`, `tests/`, `scripts/`, `.github/`, and `docs/`.
- Inventory excludes transient/generated directories unless called out explicitly:
  `src/ethernity/__pycache__/`, `.venv/`, `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`,
  `build/`, `dist/`, `kit/node_modules/`, `kit/dist/`, `src/ethernity.egg-info/`,
  `scripts/__pycache__/`, `tests/**/__pycache__/`, `src/.claude/`.

## Stable Rules (Do / Don't)

- Imports: no nested (runtime) imports; keep imports at top-level.
- Exports: prefer explicit public exports; do not re-export underscore helpers.
- Python readability with Ruff:
  - Keep `ruff format` as the only Python formatter; do not add Black for this repo.
  - Keep Python line length at 100 unless a deliberate repo-wide style change is approved.
  - Use blank lines only for real phase boundaries such as normalize, validate, execute, and report.
  - If a function needs many manual spacing groups to read clearly, split it into small named helpers.
  - Prefer module imports over long symbol lists when importing many names from one module.
  - Avoid broad barrel exports unless the re-exported surface is intentionally public.
  - In tests, replace large `mock.patch(...)` stacks with fixtures, helper context managers, or test support helpers when the same patch bundle repeats.
  - Use `# fmt: off` / `# fmt: on` only for rare, justified hotspots where structure cannot be improved.
- Text: keep ASCII-only edits unless a file already uses Unicode.
- Artifacts: do not edit generated artifacts directly; edit sources and rebuild.
- Kit bundle: do not edit `kit/dist/` or `src/ethernity/resources/kit/recovery_kit.bundle.html` directly;
  rebuild via `kit/build_kit.mjs`.
- Rendering contract: `RenderInputs` requires explicit `doc_type`; do not set
  `context["doc_type"]` and do not infer from template filename.
- Recovery rendering contract: recovery documents must provide structured
  `RenderInputs.recovery_meta`; do not infer recovery semantics by parsing `key_lines`.
- Recovery metadata source: build recovery metadata from runtime values via
  `src/ethernity/render/recovery_meta.py` (for example `build_recovery_meta(...)`) in
  backup/recovery flows, then pass it through `RenderService.recovery_inputs(...)`.
- Key line contract: treat `key_lines` as display/fallback text only; do not attach behavior to
  specific line strings.
- Template capabilities: behavior toggles belong in design style.json files (for example
  `src/ethernity/resources/templates/forge/style.json`) under the `capabilities` object, not ad-hoc
  template-name checks.
- Layout diagnostics: use `RenderInputs.layout_debug_json_path` when layout diagnostics are needed;
  this emits a JSON sidecar and should not alter render behavior.
- Template designs: discovery/prompt surfaces must expose only supported design names:
  `archive`, `forge`, `ledger`, `maritime`, `sentinel`.
  Legacy aliases or stale copied names must not be surfaced. Enforcement point:
  `src/ethernity/config/installer.py`.
- Forge icons: Forge templates must use local material symbols assets via
  `src/ethernity/resources/templates/_shared/partials/material_symbols_local.j2`; do not depend on remote
  icon CDNs.
- Recovery kit index: backup flow may emit a separate `recovery_kit_index.pdf` when the active
  template design provides a compatible `kit_index_document.html.j2`.
- CLI prompts: Questionary is the only prompt library for CLI UI.
- Fallback parser contract: for fallback section filtering, non-empty normalized lines that contain
  characters outside the z-base-32 alphabet must be treated as invalid input (reject), not silently
  discarded.
- Shard version typing: shard payload `version` validation must require a strict integer value
  (`int == 1`); bool and non-integer numeric values are out of profile and must be rejected.
- Format spec source of truth: `docs/format.md` is the only normative format specification.
- Format rationale and operations: keep non-normative guidance in `docs/format_notes.md`.
- Format change ledger: append each format-related delta to `docs/format_changes.md` with
  compatibility and version/profile bump rationale.
- Format PR discipline: when normative format behavior changes, update spec + implementation + tests
  in the same change.

## Architecture Notes

### CLI

- Entry point and command wiring: `src/ethernity/cli/bootstrap/app.py`,
  `src/ethernity/cli/bootstrap/registry.py`.
- Core command surfaces: `backup`, `recover`, `kit`, `config`, `render`.
- Command definitions live in `src/ethernity/cli/features/*/command.py`.
- Shared CLI infrastructure lives in `src/ethernity/cli/shared/`.
- Feature orchestration lives in `src/ethernity/cli/features/`; keep planning and execution
  separated where possible.

### Rendering

- Primary pipeline: spec + model + template + geometry/layout + page assembly + PDF render.
- Shared fallback/layout heuristics are centralized in `src/ethernity/render/layout_policy.py`.
- Geometry profiles are the source of truth for fallback line capacity tuning; prefer profile/style
  adjustments over template-specific branching.
- Page assembly must fail fast when fallback content cannot consume any lines on a page (zero
  capacity with remaining fallback), rather than looping or silently degrading output.
- Template style parsing and capability gates are in
  `src/ethernity/render/template_style.py`.
- Supported capability keys in template style.json files:
  - `inject_forge_copy`
  - `repeat_primary_qr_on_shard_continuation`
  - `advanced_fallback_layout`
  - `extra_main_first_page_qr_slot`
  - `uniform_main_qr_capacity`
  - `repeat_main_instructions_on_all_pages`
  - `main_qr_grid_size_mm`
  - `main_qr_grid_max_cols`
  - `fallback_layout` (requires `recovery`, `shard`, `signing_key_shard` geometry profiles)
- HTML-to-PDF conversion is isolated in `src/ethernity/render/html_to_pdf.py`.
- DOCX envelope rendering is isolated in `src/ethernity/render/docx_render.py`.
- Storage envelope template path/size helpers are in `src/ethernity/render/storage_paths.py`.

### Kit and Assets

- Browser kit app source is under `kit/app/` and `kit/lib/`.
- Built kit outputs (lean + scanner variants) live in `kit/dist/` and are copied into
  `src/ethernity/resources/kit/` by `kit/build_kit.mjs`.
- Local Material Symbols font asset:
  `src/ethernity/resources/templates/_shared/assets/material-symbols-outlined.ttf`.

## Inventory Contract (Glob-Based)

Use this section as the authoritative inventory contract for the repository.
Paths are maintained by scope globs rather than exhaustive file-by-file lists.

### Source and Runtime Code

- `src/ethernity/**/*.py`
- `src/ethernity/py.typed`
- `src/ethernity/resources/**/*`

### Browser Kit

- `kit/app/**/*`
- `kit/lib/**/*`
- `kit/scripts/**/*`
- `kit/tests/**/*`
- `kit/build_kit.mjs`
- `kit/package.json`
- `kit/package-lock.json`
- `kit/recovery_kit.html`

### Tests

- `tests/**/*.py`
- `tests/fixtures/**/*`

### Scripts and Automation

- `install.ps1`
- `scripts/*`
- `.github/workflows/*`
- `.github/actions/setup-python/action.yml`
- `.github/dependabot.yml`

### Docs

- `docs/*.md`

### Critical Anchor Files

These paths are high-signal anchors that should remain present and accurate:

- `src/ethernity/cli/bootstrap/app.py`
- `src/ethernity/config/install.py`
- `src/ethernity/render/template_style.py`
- `src/ethernity/core/bounds.py`
- `docs/format.md`
- `docs/format_notes.md`
- `docs/format_changes.md`
- `docs/release_artifacts.md`

### Inventory Maintenance Rules

- New files under the listed globs are in scope without AGENTS updates.
- Update this file when architecture contracts, capability keys, or anchor files change.
- Do not treat excluded transient/generated paths as authoritative inventory.

## Tooling and CI

- Python package/runtime target is 3.11+ (`pyproject.toml` and CI are pinned to 3.11).
- Use `uv` for dependency management and command execution.
- Static checks:
  - Ruff (`E`, `F`, `I`; line length 100)
  - Mypy (`warn_redundant_casts`, `warn_unused_ignores`)
- CI (`.github/workflows/ci.yml`) covers Ruff, formatting check, Mypy, unit/integration tests,
  coverage, and kit bundle verification/build.
- Release pipeline (`.github/workflows/pyinstaller.yml`) produces PyInstaller artifacts.
- Homebrew tap pipeline (`.github/workflows/homebrew-tap.yml`) updates tap formulae on
  release/tag events and can publish bottle metadata.
- Nuitka scripts in `scripts/build_nuitka.sh` and `scripts/build_nuitka.ps1` are local/experimental
  build helpers, not current release pipeline.

## Common Commands

- Unit tests: `uv run pytest tests/unit -v`
- Integration tests: `uv run pytest tests/integration -v`
- E2E tests: `uv run pytest tests/e2e -v`
- Coverage: `uv run pytest tests/unit tests/integration --cov=ethernity --cov-report=term-missing`
- Pre-commit: `uv run pre-commit run --all-files`
- Ruff lint: `uv run ruff check src tests`
- Ruff format check: `uv run ruff format --check src tests`
- Mypy: `uv run mypy src`
- Pyright: `uv run pyright`
- Schema validation: `uv run check-jsonschema --check-metaschema docs/cli_api.schema.json`
- Typos: `uv run typos .`
- CLI help surface: `uv run ethernity --help`
- Backup command help: `uv run ethernity backup --help`
- Recover command help: `uv run ethernity recover --help`
- Kit command help: `uv run ethernity kit --help`
- Render command help: `uv run ethernity render --help`
- Kit lint: `cd kit && npm run lint`
- Kit format check: `cd kit && npm run format:check`
- Kit tests: `cd kit && npm test`
- Envelope PDF render: `uv run ethernity render envelope-c6 --format pdf -o envelope_c6.pdf`
- Envelope DOCX render: `uv run ethernity render envelope-c6 --format docx -o envelope_c6.docx`
- Kit bundle rebuild (requires `libdeflate-gzip`): `cd kit && npm ci && node build_kit.mjs`
- PyInstaller local build (bash): `scripts/build_pyinstaller.sh`
- PyInstaller local build (PowerShell): `scripts/build_pyinstaller.ps1`
- Nuitka local build (bash): `scripts/build_nuitka.sh` with `--standalone`
- Nuitka local build (PowerShell): `scripts/build_nuitka.ps1` with `--standalone`

## Runtime Notes

- Playwright Chromium is required for HTML-to-PDF rendering. Startup install checks are handled by
  `src/ethernity/cli/bootstrap/startup.py`.
- Set `ETHERNITY_SKIP_PLAYWRIGHT_INSTALL=1` to skip Playwright downloads in tests/controlled envs.
- Set `ETHERNITY_RENDER_JOBS` to tune QR render concurrency in `src/ethernity/render/pdf_render.py`
  (`auto` or a positive integer).
- Forge icon glyphs are rendered through local font assets injected by PDF resource mapping; keep
  `src/ethernity/resources/templates/_shared/assets/material-symbols-outlined.ttf` available.
