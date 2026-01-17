# AGENTS.md

## Purpose

This repo contains a Python CLI and a browser-based recovery kit. This file records stable
conventions and a high-signal map of where things live.

## Stable Rules (Do / Don't)

- Imports: no nested (runtime) imports; keep imports at the top of files.
- Exports: prefer explicit public exports; do not re-export underscore helpers.
- Text: keep ASCII-only edits unless a file already uses Unicode.
- Artifacts: avoid editing build artifacts; work in `src/`.
- Kit bundle: do not edit `kit/dist/` or `src/ethernity/kit/recovery_kit.bundle.html` directly;
  rebuild via `kit/build_kit.mjs`.
- Rendering: `RenderInputs` requires explicit `doc_type`; do not set `context["doc_type"]` and do not
  infer from template filenames.
- CLI prompts: Questionary is the only prompt library for the CLI UI.

## Codebase Map

### Python package (`src/ethernity`)

- `cli/`: Typer entrypoint (`cli/app.py`), registry (`cli/command_registry.py`), startup helpers
  (`cli/startup.py`), commands in `cli/commands/`.
- `cli/core/`: shared CLI types, plan helpers, crypto/log utilities.
- `cli/flows/`: orchestration + pure planning
  - backup: `backup.py` / `backup_wizard.py` / `backup_plan.py` / `backup_flow.py`
  - recover: `recover_flow.py` / `recover_plan.py` / `recover_wizard.py`
- `cli/io/`: input/output helpers
  - fallback parsing is pure in `cli/io/fallback_parser.py`
  - QR/fallback ingestion and validation lives in `cli/io/frames.py`
- `cli/ui/`: Questionary + Rich UI; `cli/ui/state.py` holds `UIContext`; `cli/api.py` exports public
  UI helpers (no underscore re-exports).
- `core/`: domain models + validation (`core/models.py`, `core/validation.py`).
- `formats/`: envelope/manifest encoding + decoding (`formats/envelope_codec.py`,
  `formats/envelope_types.py`).
- `encoding/`: framing/transport encoding
  - binary frame encoding: `encoding/framing.py`
  - frame chunking/reassembly: `encoding/chunking.py`
  - QR payload encoding: `encoding/qr_payloads.py`
  - z-base-32 encode/decode: `encoding/zbase32.py`
  - formatting (line wrapping / grouping) is render-layer, not encoding-layer
- `crypto/`: age passphrase runtime, signing, sharding, etc.
- `render/`: typed spec pipeline, HTML templating, and PDF rendering (driven by `render/service.py`)
  - layout: `render/layout.py`, pages: `render/pages.py`, PDF: `render/pdf_render.py`
  - Playwright rendering isolated in `render/html_to_pdf.py`
  - fallback text formatting lives in `render/fallback_text.py`
- `config/`: user config discovery/initialization and TOML parsing.
- `qr/`: QR scanning + capacity helpers.

### Kit (browser app) (`kit/`)

- Preact entry: `kit/app/index.jsx`, main component `kit/app/App.jsx`.
- Steps: `kit/app/steps.jsx`; common UI shells in `kit/app/components/`.
- State: `kit/app/state/initial.js`, `kit/app/state/reducer.js`, selectors in
  `kit/app/state/selectors.js`.
- Domain logic: `kit/app/frames.js`, `kit/app/shards.js`, `kit/app/envelope.js`, `kit/app/auth.js`.
- Browser crypto/format helpers: `kit/lib/`.
- HTML shell: `kit/recovery_kit.html`.
- Bundle script: `kit/build_kit.mjs` (esbuild + html-minifier + gzip), outputs to `kit/dist/` and
  copies into `src/ethernity/kit/` as `recovery_kit.bundle.html`.

## Documentation

- `docs/format.md` is the normative, language-agnostic core format specification (protocol-style).
- `docs/format_notes.md` is non-normative rationale/operational guidance and implementation notes.

## Tooling and CI

- Use `uv` for Python tooling and installs.
- Ruff and Mypy are enforced:
  - Ruff config in `pyproject.toml` (line length 100, select E/F/I).
  - Mypy with `warn_redundant_casts` and `warn_unused_ignores`.
- CI workflows:
  - `.github/workflows/ci.yml`: Ruff lint/format, Mypy, pytest (unit + integration), coverage, kit
    bundle verification/build (Node 20).
  - `.github/workflows/pyinstaller.yml`: release artifacts (see `scripts/`).
  - `.github/actions/setup-python`: `uv sync`, defaults to Python 3.13.

## Common Commands

- Tests (unit): `uv run pytest tests/unit -v`
- Tests (integration): `uv run pytest tests/integration -v`
- Tests (e2e): `uv run pytest tests/e2e -v`
- Coverage: `uv run pytest tests/unit tests/integration --cov=ethernity --cov-report=term-missing`
- Ruff lint: `uv run --extra dev ruff check src tests`
- Ruff format check: `uv run --extra dev ruff format --check src tests`
- Mypy: `uv run --extra dev mypy src`
- Build kit bundle: `cd kit && npm ci && node build_kit.mjs`

## Runtime Notes

- Playwright Chromium is required for PDF rendering; `cli/startup.py` manages install.
  Set `ETHERNITY_SKIP_PLAYWRIGHT_INSTALL=1` to skip downloads in tests.
