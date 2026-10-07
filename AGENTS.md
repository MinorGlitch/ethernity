# AGENTS.md

## Purpose

This file contains stable operating rules for coding agents in this repository. Keep it short,
durable, and source-linked. Do not turn it into a copied inventory of the codebase; copied
inventories go stale faster than code.

Ethernity is a Python CLI/Textual app with a browser-based recovery kit. Treat cryptography,
format compatibility, recovery behavior, rendering output, and packaging as high-risk areas.

## First moves

- Start from the current working tree, including uncommitted and untracked files.
- Check `git status --short` before editing. Assume existing changes belong to the user.
- Use `rg`/`rg --files` for search. Read the nearby code before changing behavior.
- Prefer the narrowest change that satisfies the task and fits existing module boundaries.
- Do not preserve a rule here just because it is written here. Verify against the source of truth
  below when a rule, command, or path looks stale.

## Source of truth

- Python package metadata, dependency groups, Ruff, Pyrefly, pytest, and coverage settings:
  `pyproject.toml`.
- Scriptable task commands: `src/ethernity/run/command_registry.py` and
  `src/ethernity/run/cli.py`.
- CI gates and release checks: `.github/workflows/ci.yml`,
  `.github/workflows/pyinstaller.yml`, and `.github/workflows/homebrew-tap.yml`.
- Normative format specification: `docs/format.md`.
- Normative v1.2 extension publication rules: `docs/extension_publication_rules.md`.
- Format rationale and recovery guidance: `docs/format_rationale.md`.
- Format compatibility history: `docs/format_history.md`.
- Render design definitions, style settings, and capabilities:
  `src/ethernity/resources/designs/*/style.json`,
  `src/ethernity/resources/designs/*/design.json`,
  `src/ethernity/render/template.py`, and `src/ethernity/render/design_style.py`.
- Browser kit commands and dependencies: `kit/package.json` and `kit/package-lock.json`.
- Packaging contents: `pyproject.toml`, `ethernity.spec`, `tooling/release_resources.py`,
  and the release workflows.

## Working tree safety

- Never revert, reset, delete, or overwrite user changes unless the user explicitly asks.
- If user changes touch files you must edit, read them carefully and work with them.
- If unrelated files are dirty, leave them alone.
- Do not use destructive Git commands such as `git reset --hard` or `git checkout --` without
  explicit user approval.
- Keep generated or incidental metadata churn out of your patch.

## Architecture boundaries

- `src/ethernity/app/`: Textual UI, screens, widgets, bindings, and UI state wiring only.
  Do not hide domain rules here.
- `src/ethernity/run/`: Click-based scriptable commands and command output handling.
  Keep command flags thin; delegate validation and execution to task/domain layers.
- `src/ethernity/tasks/`: task state, validation, preview, execution adapters, and presentation
  models shared by the app and command runner.
- `src/ethernity/workflows/`: adapter-neutral application use cases with typed requests, issues,
  assessments, and execution results. Do not accept CLI argument models or return UI/JSON models.
- `src/ethernity/workflows/shared/`: shared workflow input, output, inspection, and reporting
  types. The removed `src/ethernity/cli/` tree must not be recreated.
- `src/ethernity/render/`: render interfaces, layout policy, design/style parsing, and backend
  dispatch. Rendering behavior should be driven by typed inputs, geometry, and style capabilities,
  not by ad-hoc style-name checks.
- `src/ethernity/render/direct_pdf/`: direct PDF implementation details. Keep backend-specific
  drawing behind the local surface/component abstractions.
- `src/ethernity/formats/`, `src/ethernity/encoding/`, `src/ethernity/crypto/`,
  `src/ethernity/extensions/`, and `src/ethernity/qr/`: format, recovery, crypto, extension,
  and QR processing. Do not couple these modules to UI text or display layout.
- `kit/`: browser recovery kit source and tests. Generated bundles are not source.

If a change needs behavior from another layer, add a clear typed boundary or
reuse an existing service. Do not reach across layers with string parsing, duplicated rules, or
"just this once" imports.

## Stable coding conventions

- Keep imports at module top level. Avoid nested runtime imports.
- Prefer explicit public exports. Do not re-export underscore-prefixed implementation functions.
- Use `ruff format` as the only Python formatter. Do not add Black.
- Keep Python line length at 100 unless a deliberate repo-wide style change is approved.
- Prefer small named functions over dense coordinators or manual spacing tricks.
- Prefer module imports over long symbol lists when importing many names from one module.
- Use blank lines for real phase boundaries such as normalize, validate, execute, and report.
- Use `# fmt: off` / `# fmt: on` only for rare cases where structure cannot be improved.
- Keep ASCII-only edits unless a file already uses Unicode or the change clearly requires it.
- In tests, replace repeated `mock.patch(...)` stacks with fixtures, focused context managers, or
  shared test setup.

## Generated files

- Do not edit generated files directly.
- Do not edit or stage generated recovery kit bundles under
  `src/ethernity/resources/kit/recovery_kit*.bundle.html`; rebuild from `kit/` when packaging
  work requires them.
- Treat `build/`, `dist/`, `kit/dist/`, `kit/node_modules/`, cache directories, and egg-info
  directories as transient unless the user explicitly asks about them.
- Golden fixtures and visual baselines have compatibility value. Regenerate them
  through the relevant scripts/tests and explain why when behavior intentionally changes.

## Change guidance

### Format or recovery behavior

- Update `docs/format.md` for normative behavior.
- Update `docs/extension_publication_rules.md` for published extension layout, recovery documents,
  recovery-kit, selected-version recovery, replacement-sheet, or Rebuild behavior.
- Update `docs/format_rationale.md` for rationale or operational guidance.
- Update `docs/format_history.md` only when the behavior is a compatibility-relevant delta. Before
  adding a new entry, check whether the behavior was introduced earlier on the same unreleased
  branch; if so, update that entry instead.
- Update implementation and tests in the same change. Include negative/error-path tests for parser,
  shard, recovery, or compatibility behavior.

### Rendering and layout

- Templates are JSON data. Keep document composition in the shared engine and add reusable
  layout features through its components and validated template settings. Do not add per-design
  Python builders or registration tables. See `docs/render_templates.md`.
- `RenderInputs` must carry explicit `doc_type`. Do not infer document type from design names and
  do not smuggle behavior through `context["doc_type"]`.
- Recovery documents must use typed `RenderInputs.recovery_meta`; do not infer recovery
  behavior by parsing display `key_lines`.
- Treat `key_lines` as display/fallback text only.
- Put style behavior toggles in style `capabilities`, parsed by
  `src/ethernity/render/design_style.py`.
- Use `RenderInputs.layout_debug_json_path` for layout diagnostics. Diagnostics must not change
  render behavior.
- Layout code should fail fast on impossible pagination or zero-capacity fallback pages rather than
  loop or silently degrade.

### CLI, Textual app, and tasks

- `ethernity` is the human Textual app. Do not reintroduce prompt-loop UI libraries such as
  Questionary or prompt-toolkit.
- Scriptable usage lives under `ethernity run ...`; use the command registry as the current command
  list.
- Keep Textual widgets focused on editing and presenting task state. Task validation, preview, and
  execution belong in task/domain layers.
- Do not duplicate user-facing behavior in both app and command code. Share task models and
  services where possible.

### Browser kit

- Edit source under `kit/app/`, `kit/lib/`, `kit/scripts/`, and `kit/tests/`.
- Run kit lint, format check, and tests when touching kit behavior.
- Rebuild bundles with `node build_kit.mjs` only when package/release validation requires generated
  kit resources.

### Packaging and release

- Keep package data in `pyproject.toml` aligned with actual runtime resources.
- Keep PyInstaller and release scripts aligned with generated kit and design assets.
- When release files change, update `docs/release_files.md` if user-facing expectations
  change.

## Verification matrix

Choose the smallest verification set that proves the change. Prefer targeted tests during
iteration, then broader gates before handoff when risk is high.

- Python lint: `uv run ruff check src tests tooling`
- Python format check: `uv run ruff format --check src tests tooling`
- Python duplication and nesting: `uv run pylint src/ethernity tooling`
- Type check: `uv run pyrefly check`
- Typos: `uv run typos .`
- Unit tests: `uv run pytest tests/unit -v`
- Integration tests: `uv run pytest tests/integration -v`
- E2E tests: `uv run pytest tests/e2e -v`
- Coverage gate:
  `uv run pytest tests/unit tests/integration --cov=ethernity --cov-report=term-missing`
- CLI help: `uv run ethernity --help` and `uv run ethernity run --help`
- Kit lint: run `npm run lint` from `kit/`
- Kit format check: run `npm run format:check` from `kit/`
- Kit tests: run `npm test` from `kit/`
- Kit bundle rebuild: run `npm ci` if dependencies are missing, then `node build_kit.mjs`
  from `kit/`

## When to update this file

Update `AGENTS.md` when a repo-wide, stable agent rule changes. Do not update it for local machine
preferences, temporary plans, exhaustive file inventories, stale command lists, or facts already
owned by source code, config, CI, or docs.

Before adding a rule, ask:

- Is it repo-wide rather than personal or task-local?
- Is it expected to remain true across branches?
- Is this the best source of truth, or should the rule live next to code/config/docs instead?
- Will it help agents avoid real mistakes without encouraging broad rewrites?
