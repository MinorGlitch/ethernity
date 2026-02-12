# AGENTS.md

## Purpose

This repository contains a Python CLI and a browser-based recovery kit. This file defines stable
conventions and a strict, working-tree inventory for contributors and coding agents.

## Scope and Baseline

- Baseline: the current working tree (including uncommitted and untracked files).
- Inventory scope: `src/`, `kit/`, `tests/`, `scripts/`, `.github/`, and `docs/`.
- Inventory excludes transient/generated directories unless called out explicitly:
  `src/ethernity/__pycache__/`, `.venv/`, `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`,
  `build/`, `dist/`,
  `kit/node_modules/`.

## Stable Rules (Do / Don't)

- Imports: no nested (runtime) imports; keep imports at top-level.
- Exports: prefer explicit public exports; do not re-export underscore helpers.
- Text: keep ASCII-only edits unless a file already uses Unicode.
- Artifacts: do not edit generated artifacts directly; edit sources and rebuild.
- Kit bundle: do not edit `kit/dist/` or `src/ethernity/kit/recovery_kit.bundle.html` directly;
  rebuild via `kit/build_kit.mjs`.
- Rendering contract: `RenderInputs` requires explicit `doc_type`; do not set
  `context["doc_type"]` and do not infer from template filename.
- Template capabilities: behavior toggles belong in design style.json files (for example
  `src/ethernity/templates/forge/style.json`) under the `capabilities` object, not ad-hoc
  template-name checks.
- Forge icons: Forge templates must use local material symbols assets via
  `src/ethernity/templates/_shared/partials/material_symbols_local.j2`; do not depend on remote
  icon CDNs.
- Recovery kit index: backup flow may emit a separate `recovery_kit_index.pdf` when a compatible
  `src/ethernity/templates/forge/kit_index_document.html.j2` style of index template is available.
- CLI prompts: Questionary is the only prompt library for CLI UI.

## Architecture Notes

### CLI

- Entry point and command wiring: `src/ethernity/cli/app.py`,
  `src/ethernity/cli/command_registry.py`.
- Core command surfaces: `backup`, `recover`, `kit`, `config`, `render`.
- Orchestration is in `src/ethernity/cli/flows/`; keep planning and execution separated where
  possible.
- Key recovery helpers live in `src/ethernity/cli/keys/`.

### Rendering

- Primary pipeline: spec + model + template + geometry/layout + page assembly + PDF render.
- Shared fallback/layout heuristics are centralized in `src/ethernity/render/layout_policy.py`.
- Template style parsing and capability gates are in
  `src/ethernity/render/template_style.py`.
- Supported capability keys in template style.json files:
  - `repeat_primary_qr_on_shard_continuation`
  - `advanced_fallback_layout`
- HTML-to-PDF conversion is isolated in `src/ethernity/render/html_to_pdf.py`.
- DOCX envelope rendering is isolated in `src/ethernity/render/docx_render.py`.
- Storage envelope template path/size helpers are in `src/ethernity/render/storage_paths.py`.

### Kit and Assets

- Browser kit app source is under `kit/app/` and `kit/lib/`.
- Built kit outputs live in `kit/dist/` and are copied into `src/ethernity/kit/` by
  `kit/build_kit.mjs`.
- Local Material Symbols font asset:
  `src/ethernity/templates/_shared/assets/material-symbols-outlined.ttf`.

## Strict Inventory

### Python Package: `src/ethernity`

- Package root:
  - `src/ethernity/__init__.py`
  - `src/ethernity/__main__.py`
  - `src/ethernity/py.typed`

- CLI root:
  - `src/ethernity/cli/__init__.py`
  - `src/ethernity/cli/__main__.py`
  - `src/ethernity/cli/api.py`
  - `src/ethernity/cli/app.py`
  - `src/ethernity/cli/command_registry.py`
  - `src/ethernity/cli/constants.py`
  - `src/ethernity/cli/startup.py`

- CLI commands:
  - `src/ethernity/cli/commands/__init__.py`
  - `src/ethernity/cli/commands/backup.py`
  - `src/ethernity/cli/commands/config.py`
  - `src/ethernity/cli/commands/kit.py`
  - `src/ethernity/cli/commands/recover.py`
  - `src/ethernity/cli/commands/render.py`

- CLI core:
  - `src/ethernity/cli/core/__init__.py`
  - `src/ethernity/cli/core/common.py`
  - `src/ethernity/cli/core/crypto.py`
  - `src/ethernity/cli/core/log.py`
  - `src/ethernity/cli/core/plan.py`
  - `src/ethernity/cli/core/text.py`
  - `src/ethernity/cli/core/types.py`

- CLI flows:
  - `src/ethernity/cli/flows/__init__.py`
  - `src/ethernity/cli/flows/backup.py`
  - `src/ethernity/cli/flows/backup_flow.py`
  - `src/ethernity/cli/flows/backup_plan.py`
  - `src/ethernity/cli/flows/backup_wizard.py`
  - `src/ethernity/cli/flows/kit.py`
  - `src/ethernity/cli/flows/prompts.py`
  - `src/ethernity/cli/flows/recover.py`
  - `src/ethernity/cli/flows/recover_flow.py`
  - `src/ethernity/cli/flows/recover_input.py`
  - `src/ethernity/cli/flows/recover_plan.py`
  - `src/ethernity/cli/flows/recover_wizard.py`

- CLI I/O:
  - `src/ethernity/cli/io/__init__.py`
  - `src/ethernity/cli/io/fallback_parser.py`
  - `src/ethernity/cli/io/frames.py`
  - `src/ethernity/cli/io/inputs.py`
  - `src/ethernity/cli/io/outputs.py`

- CLI keys:
  - `src/ethernity/cli/keys/__init__.py`
  - `src/ethernity/cli/keys/recover_keys.py`

- CLI UI:
  - `src/ethernity/cli/ui/__init__.py`
  - `src/ethernity/cli/ui/debug.py`
  - `src/ethernity/cli/ui/prompts.py`
  - `src/ethernity/cli/ui/state.py`
  - `src/ethernity/cli/ui/summary.py`

- Config:
  - `src/ethernity/config/__init__.py`
  - `src/ethernity/config/config.toml`
  - `src/ethernity/config/installer.py`
  - `src/ethernity/config/loader.py`

- Core domain:
  - `src/ethernity/core/__init__.py`
  - `src/ethernity/core/models.py`
  - `src/ethernity/core/validation.py`

- Crypto:
  - `src/ethernity/crypto/__init__.py`
  - `src/ethernity/crypto/age_runtime.py`
  - `src/ethernity/crypto/passphrases.py`
  - `src/ethernity/crypto/sharding.py`
  - `src/ethernity/crypto/signing.py`

- Encoding:
  - `src/ethernity/encoding/__init__.py`
  - `src/ethernity/encoding/cbor.py`
  - `src/ethernity/encoding/chunking.py`
  - `src/ethernity/encoding/framing.py`
  - `src/ethernity/encoding/qr_payloads.py`
  - `src/ethernity/encoding/varint.py`
  - `src/ethernity/encoding/zbase32.py`

- Formats:
  - `src/ethernity/formats/__init__.py`
  - `src/ethernity/formats/envelope_codec.py`
  - `src/ethernity/formats/envelope_types.py`

- Kit package data:
  - `src/ethernity/kit/__init__.py`
  - `src/ethernity/kit/recovery_kit.bundle.html`

- QR:
  - `src/ethernity/qr/__init__.py`
  - `src/ethernity/qr/capacity.py`
  - `src/ethernity/qr/codec.py`
  - `src/ethernity/qr/scan.py`

- Render:
  - `src/ethernity/render/__init__.py`
  - `src/ethernity/render/doc_types.py`
  - `src/ethernity/render/docx_render.py`
  - `src/ethernity/render/fallback.py`
  - `src/ethernity/render/fallback_text.py`
  - `src/ethernity/render/geometry.py`
  - `src/ethernity/render/html_to_pdf.py`
  - `src/ethernity/render/layout.py`
  - `src/ethernity/render/layout_policy.py`
  - `src/ethernity/render/pages.py`
  - `src/ethernity/render/pdf_render.py`
  - `src/ethernity/render/service.py`
  - `src/ethernity/render/spec.py`
  - `src/ethernity/render/storage_paths.py`
  - `src/ethernity/render/template_model.py`
  - `src/ethernity/render/template_style.py`
  - `src/ethernity/render/templating.py`
  - `src/ethernity/render/text.py`
  - `src/ethernity/render/types.py`
  - `src/ethernity/render/utils.py`

- Storage templates/assets:
  - `src/ethernity/storage/envelope_c4.html.j2`
  - `src/ethernity/storage/envelope_c5.html.j2`
  - `src/ethernity/storage/envelope_c6.html.j2`
  - `src/ethernity/storage/envelope_dl.html.j2`
  - `src/ethernity/storage/logo.png`

### Template Source: `src/ethernity/templates`

- Shared:
  - `src/ethernity/templates/_shared/css_base.j2`
  - `src/ethernity/templates/_shared/css_variables.j2`
  - `src/ethernity/templates/_shared/html_components.j2`
  - `src/ethernity/templates/_shared/assets/material-symbols-outlined.ttf`
  - `src/ethernity/templates/_shared/partials/forge_tailwind.j2`
  - `src/ethernity/templates/_shared/partials/material_symbols_local.j2`

- Archive:
  - `src/ethernity/templates/archive/kit_document.html.j2`
  - `src/ethernity/templates/archive/main_document.html.j2`
  - `src/ethernity/templates/archive/recovery_document.html.j2`
  - `src/ethernity/templates/archive/shard_document.html.j2`
  - `src/ethernity/templates/archive/signing_key_shard_document.html.j2`
  - `src/ethernity/templates/archive/style.json`

- Dossier:
  - `src/ethernity/templates/dossier/kit_document.html.j2`
  - `src/ethernity/templates/dossier/main_document.html.j2`
  - `src/ethernity/templates/dossier/recovery_document.html.j2`
  - `src/ethernity/templates/dossier/shard_document.html.j2`
  - `src/ethernity/templates/dossier/signing_key_shard_document.html.j2`
  - `src/ethernity/templates/dossier/style.json`

- Forge:
  - `src/ethernity/templates/forge/kit_document.html.j2`
  - `src/ethernity/templates/forge/kit_index_document.html.j2`
  - `src/ethernity/templates/forge/main_document.html.j2`
  - `src/ethernity/templates/forge/recovery_document.html.j2`
  - `src/ethernity/templates/forge/shard_document.html.j2`
  - `src/ethernity/templates/forge/signing_key_shard_document.html.j2`
  - `src/ethernity/templates/forge/style.json`

- Ledger:
  - `src/ethernity/templates/ledger/kit_document.html.j2`
  - `src/ethernity/templates/ledger/main_document.html.j2`
  - `src/ethernity/templates/ledger/recovery_document.html.j2`
  - `src/ethernity/templates/ledger/shard_document.html.j2`
  - `src/ethernity/templates/ledger/signing_key_shard_document.html.j2`
  - `src/ethernity/templates/ledger/style.json`

- Maritime:
  - `src/ethernity/templates/maritime/kit_document.html.j2`
  - `src/ethernity/templates/maritime/main_document.html.j2`
  - `src/ethernity/templates/maritime/recovery_document.html.j2`
  - `src/ethernity/templates/maritime/shard_document.html.j2`
  - `src/ethernity/templates/maritime/signing_key_shard_document.html.j2`
  - `src/ethernity/templates/maritime/style.json`

- Midnight:
  - `src/ethernity/templates/midnight/kit_document.html.j2`
  - `src/ethernity/templates/midnight/main_document.html.j2`
  - `src/ethernity/templates/midnight/recovery_document.html.j2`
  - `src/ethernity/templates/midnight/shard_document.html.j2`
  - `src/ethernity/templates/midnight/signing_key_shard_document.html.j2`
  - `src/ethernity/templates/midnight/style.json`

### Browser Kit Source: `kit/`

- App root:
  - `kit/app/App.jsx`
  - `kit/app/actions.js`
  - `kit/app/auth.js`
  - `kit/app/constants.js`
  - `kit/app/envelope.js`
  - `kit/app/frames.js`
  - `kit/app/index.jsx`
  - `kit/app/io.js`
  - `kit/app/shard_auth.js`
  - `kit/app/shards.js`
  - `kit/app/steps.jsx`

- App components:
  - `kit/app/components/CollectorStep.jsx`
  - `kit/app/components/DecryptSection.jsx`
  - `kit/app/components/FrameCollector.jsx`
  - `kit/app/components/RecoveredFiles.jsx`
  - `kit/app/components/ShardCollector.jsx`
  - `kit/app/components/StatusStrip.jsx`
  - `kit/app/components/StepNav.jsx`
  - `kit/app/components/StepShell.jsx`
  - `kit/app/components/common.jsx`

- App state:
  - `kit/app/state/initial.js`
  - `kit/app/state/reducer.js`
  - `kit/app/state/selectors.js`

- Browser crypto/libs:
  - `kit/lib/age_scrypt.js`
  - `kit/lib/blake2b.js`
  - `kit/lib/cbor.js`
  - `kit/lib/crc32.js`
  - `kit/lib/encoding.js`
  - `kit/lib/shamir.js`
  - `kit/lib/zip.js`

- Build/runtime files:
  - `kit/build_kit.mjs`
  - `kit/package.json`
  - `kit/package-lock.json`
  - `kit/recovery_kit.html`
  - `kit/scripts/run_parse_vectors.mjs`

### Tests: `tests/`

- Root/support:
  - `tests/__init__.py`
  - `tests/test_support.py`
  - `tests/fixtures/recovery_parse_vectors.json`

- E2E:
  - `tests/e2e/__init__.py`
  - `tests/e2e/test_end_to_end_cli.py`
  - `tests/e2e/test_end_to_end_sharding.py`

- Integration:
  - `tests/integration/__init__.py`
  - `tests/integration/test_integration_backup.py`
  - `tests/integration/test_integration_recover.py`

- Unit:
  - `tests/unit/__init__.py`
  - `tests/unit/test_age_cli.py`
  - `tests/unit/test_backup_args_validation.py`
  - `tests/unit/test_chunking.py`
  - `tests/unit/test_cli_backup.py`
  - `tests/unit/test_cli_flows.py`
  - `tests/unit/test_cli_recover_validation.py`
  - `tests/unit/test_cli_startup.py`
  - `tests/unit/test_cli_typer.py`
  - `tests/unit/test_cli_ui.py`
  - `tests/unit/test_config.py`
  - `tests/unit/test_envelope.py`
  - `tests/unit/test_fallback_blocks.py`
  - `tests/unit/test_fallback_parser.py`
  - `tests/unit/test_framing.py`
  - `tests/unit/test_input_files.py`
  - `tests/unit/test_jinja_templates.py`
  - `tests/unit/test_kit_vectors.py`
  - `tests/unit/test_passphrases.py`
  - `tests/unit/test_pdf_layout.py`
  - `tests/unit/test_pdf_pages.py`
  - `tests/unit/test_pdf_recovery_meta.py`
  - `tests/unit/test_pdf_render.py`
  - `tests/unit/test_qr_chunk_size.py`
  - `tests/unit/test_qr_codec.py`
  - `tests/unit/test_qr_payloads.py`
  - `tests/unit/test_qr_scan.py`
  - `tests/unit/test_qr_scan_errors.py`
  - `tests/unit/test_qr_scan_more.py`
  - `tests/unit/test_recover_input.py`
  - `tests/unit/test_recover_prompts.py`
  - `tests/unit/test_render_geometry.py`
  - `tests/unit/test_render_pages.py`
  - `tests/unit/test_render_spec.py`
  - `tests/unit/test_render_text.py`
  - `tests/unit/test_sharding.py`
  - `tests/unit/test_signing.py`
  - `tests/unit/test_template_style.py`
  - `tests/unit/test_templating_shared_dir.py`
  - `tests/unit/test_validation.py`

### Scripts: `scripts/`

- `scripts/build_pyinstaller.sh`
- `scripts/build_pyinstaller.ps1`
- `scripts/package_pyinstaller.py`
- `scripts/build_nuitka.sh`
- `scripts/build_nuitka.ps1`

### GitHub: `.github/`

- Workflows:
  - `.github/workflows/ci.yml`
  - `.github/workflows/pyinstaller.yml`

- Composite action:
  - `.github/actions/setup-python/action.yml`

- Other repo automation/config:
  - `.github/dependabot.yml`
  - `.github/ISSUE_TEMPLATE/open-source-readiness.md`

### Docs: `docs/`

- `docs/format.md`
- `docs/format_notes.md`

## Tooling and CI

- Python package/runtime target is 3.13+ (`pyproject.toml` and CI are pinned to 3.13).
- Use `uv` for dependency management and command execution.
- Static checks:
  - Ruff (`E`, `F`, `I`; line length 100)
  - Mypy (`warn_redundant_casts`, `warn_unused_ignores`)
- CI (`.github/workflows/ci.yml`) covers Ruff, formatting check, Mypy, unit/integration tests,
  coverage, and kit bundle verification/build.
- Release pipeline (`.github/workflows/pyinstaller.yml`) produces PyInstaller artifacts.
- Nuitka scripts in `scripts/build_nuitka.sh` and `scripts/build_nuitka.ps1` are local/experimental
  build helpers, not current release pipeline.

## Common Commands

- Unit tests: `uv run pytest tests/unit -v`
- Integration tests: `uv run pytest tests/integration -v`
- E2E tests: `uv run pytest tests/e2e -v`
- Coverage: `uv run pytest tests/unit tests/integration --cov=ethernity --cov-report=term-missing`
- Ruff lint: `uv run ruff check src tests`
- Ruff format check: `uv run ruff format --check src tests`
- Mypy: `uv run mypy src`
- CLI help surface: `uv run ethernity --help`
- Backup command help: `uv run ethernity backup --help`
- Recover command help: `uv run ethernity recover --help`
- Kit command help: `uv run ethernity kit --help`
- Render command help: `uv run ethernity render --help`
- Envelope PDF render: `uv run ethernity render envelope-c6 --format pdf -o envelope_c6.pdf`
- Envelope DOCX render: `uv run ethernity render envelope-c6 --format docx -o envelope_c6.docx`
- Kit bundle rebuild: `cd kit && npm ci && node build_kit.mjs`
- PyInstaller local build (bash): `scripts/build_pyinstaller.sh`
- PyInstaller local build (PowerShell): `scripts/build_pyinstaller.ps1`
- Nuitka local build (bash): `scripts/build_nuitka.sh --standalone`
- Nuitka local build (PowerShell): `scripts/build_nuitka.ps1 --standalone`

## Runtime Notes

- Playwright Chromium is required for HTML-to-PDF rendering. Startup install checks are handled by
  `src/ethernity/cli/startup.py`.
- Set `ETHERNITY_SKIP_PLAYWRIGHT_INSTALL=1` to skip Playwright downloads in tests/controlled envs.
- Set `ETHERNITY_RENDER_JOBS` to tune QR render concurrency in `src/ethernity/render/pdf_render.py`
  (`auto` or a positive integer).
- Forge icon glyphs are rendered through local font assets injected by PDF resource mapping; keep
  `src/ethernity/templates/_shared/assets/material-symbols-outlined.ttf` available.
