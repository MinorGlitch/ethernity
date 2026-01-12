AGENTS.md

Overview
- Repository: ethernity (Python CLI + browser-based recovery kit).
- Source layout: Python package lives in `src/ethernity` (not `ethernity/`).
- Kit app lives in `kit/` and is bundled into `src/ethernity/kit`.

Project layout (Python)
- `src/ethernity/cli`: Typer entrypoint (`app.py`), command registry (`command_registry.py`),
  startup helpers (`startup.py`), and commands in `cli/commands/`.
- `src/ethernity/cli/core`: Shared CLI types, plan helpers, crypto/log utilities.
- `src/ethernity/cli/flows`: Orchestration and pure planning:
  - Backup: `backup.py` (wizard orchestration), `backup_wizard.py` (prompt logic),
    `backup_plan.py` (plan building), `backup_flow.py` (crypto/render execution).
  - Recovery: `recover_flow.py` (CLI flow), `recover_plan.py` (pure plan),
    `recover_wizard.py` (interactive flow).
- `src/ethernity/cli/keys`: Key recovery helpers (`recover_keys.py`).
- `src/ethernity/cli/ui`: Questionary + Rich UI; `ui/state.py` holds `UIContext`;
  `cli/api.py` exports public UI helpers (no underscore re-exports).
- `src/ethernity/cli/io`: Input/output helpers; fallback parsing is pure in
  `cli/io/fallback_parser.py`, warnings/IO live in `cli/io/frames.py`.
- `src/ethernity/core`: Domain models and validation (`models.py`, `validation.py`).
- `src/ethernity/render`: Typed spec pipeline, HTML templating, and PDF rendering.
- `src/ethernity/config`: User config discovery/initialization and TOML parsing.
- `src/ethernity/crypto`, `src/ethernity/encoding`, `src/ethernity/formats`, `src/ethernity/qr`:
  crypto, payload framing/encoding, envelope format, and QR scanning.

Rendering pipeline
- Typed specs in `src/ethernity/render/spec.py` and layout in `src/ethernity/render/layout.py`.
- Page assembly in `src/ethernity/render/pages.py`; PDF rendering in `src/ethernity/render/pdf_render.py`.
- `RenderInputs` requires explicit `doc_type`; do not set `context["doc_type"]`
  and do not infer from template filenames.
- Doc type constants in `src/ethernity/render/doc_types.py`.
- Playwright rendering isolated in `src/ethernity/render/html_to_pdf.py`.
- Rendering is driven via `RenderService` in `src/ethernity/render/service.py`.

Config and templates
- Templates are HTML Jinja in `src/ethernity/templates`.
- Kit PDF template: `src/ethernity/templates/kit_document.html.j2`.
- Config presets in `src/ethernity/config` (`a4.toml`, `letter.toml`).
- Config paths are computed lazily in `src/ethernity/config/installer.py`;
  loader expands `~` and `$VARS` in `src/ethernity/config/loader.py`.

Kit (browser app)
- Preact app: entry `kit/app/index.jsx`, main component `kit/app/App.jsx`.
- Steps config in `kit/app/steps.jsx`; StepShell/StepNav in `kit/app/components/`.
- State in `kit/app/state/initial.js`, `reducer.js`, and selectors in `state/selectors.js`.
- Actions in `kit/app/actions.js` and domain logic in `kit/app/frames.js`,
  `kit/app/shards.js`, `kit/app/envelope.js`, `kit/app/auth.js`.
- Browser crypto/format helpers live in `kit/lib`.
- HTML shell template: `kit/recovery_kit.html`.
- Bundle script: `kit/build_kit.mjs` (esbuild + html-minifier + gzip), outputs to
  `kit/dist/` and copies into `src/ethernity/kit` as `recovery_kit.bundle.html`.

Tooling and CI
- Use uv for Python tooling and installs.
- Ruff and Mypy enforced:
  - Ruff config in `pyproject.toml` (line length 100, select E/F/I).
  - Mypy with `warn_redundant_casts` and `warn_unused_ignores`.
- CI workflows:
  - `.github/workflows/ci.yml` runs Ruff lint/format, Mypy, pytest (unit + integration),
    coverage, and kit bundle verification/build (Node 20).
  - `.github/workflows/pyinstaller.yml` builds release artifacts (see `scripts/`).
  - `.github/actions/setup-python` uses uv sync and defaults to Python 3.13.

Core conventions
- No nested (runtime) imports; keep imports at the top of files.
- Prefer explicit public exports; do not re-export underscore helpers.
- Keep ASCII-only edits unless a file already uses Unicode.
- Avoid editing build artifacts; work in `src/`.
- Do not edit `kit/dist` or `src/ethernity/kit/recovery_kit.bundle.html` directly;
  rebuild via `kit/build_kit.mjs`.

Common commands
- Tests (unit): `uv run pytest tests/unit -v`
- Tests (integration): `uv run pytest tests/integration -v`
- Tests (e2e): `uv run pytest tests/e2e -v`
- Coverage: `uv run pytest tests/unit tests/integration --cov=ethernity --cov-report=term-missing`
- Ruff lint: `uv run --extra dev ruff check src tests`
- Ruff format check: `uv run --extra dev ruff format --check src tests`
- Mypy: `uv run --extra dev mypy src`
- Build kit bundle: `cd kit && npm ci && node build_kit.mjs`

Important notes
- Rendering requires explicit `doc_type` in `RenderInputs`.
- Questionary is the only prompt library for the CLI UI.
- Playwright Chromium is required for PDF rendering; `cli/startup.py` manages install.
  Set `ETHERNITY_SKIP_PLAYWRIGHT_INSTALL=1` to skip downloads in tests.
