# AGENTS.md

## Purpose

This file is the stable operating contract for coding agents in this repository. Keep it short,
durable, and source-linked. Do not turn it into a copied inventory of the codebase; copied
inventories go stale faster than code.

Ethernity is a Python CLI/Textual app with a browser-based recovery kit. Treat cryptography,
format compatibility, recovery behavior, rendering output, and packaging as high-risk surfaces.

## First Moves

- Start from the current working tree, including uncommitted and untracked files.
- Check `git status --short` before editing. Assume existing changes belong to the user.
- Use `rg`/`rg --files` for search. Read the nearby code before changing behavior.
- Prefer the narrowest change that satisfies the task and fits existing module boundaries.
- Do not preserve a rule here just because it is written here. Verify against the source of truth
  below when a rule, command, or path looks stale.

## Source Of Truth

- Python package metadata, dependency groups, Ruff, Pyrefly, pytest, and coverage settings:
  `pyproject.toml`.
- Scriptable task commands: `src/ethernity/run/command_registry.py` and
  `src/ethernity/run/cli.py`.
- CI gates and release checks: `.github/workflows/ci.yml`,
  `.github/workflows/pyinstaller.yml`, and `.github/workflows/homebrew-tap.yml`.
- Normative format specification: `docs/format.md`.
- Normative v1.2 extension operations and publication profile:
  `docs/extension_publication_profile.md`.
- Format rationale and operations: `docs/format_notes.md`.
- Format compatibility ledger: `docs/format_changes.md`.
- Render style manifests and capabilities:
  `src/ethernity/resources/templates/*/style.json`,
  `src/ethernity/resources/templates/*/design.json`, and
  `src/ethernity/render/template_style.py`.
- Browser kit commands and dependencies: `kit/package.json` and `kit/package-lock.json`.
- Packaging contents: `pyproject.toml`, `ethernity.spec`, `scripts/check_wheel_contents.py`,
  and the release workflows.

## Working Tree Safety

- Never revert, reset, delete, or overwrite user changes unless the user explicitly asks.
- If user changes touch files you must edit, read them carefully and work with them.
- If unrelated files are dirty, leave them alone.
- Do not use destructive Git commands such as `git reset --hard` or `git checkout --` without
  explicit user approval.
- Keep generated or incidental metadata churn out of your patch.

## Architecture Boundaries

- `src/ethernity/app/`: Textual UI, screens, widgets, bindings, and UI state wiring only.
  Do not hide domain rules here.
- `src/ethernity/run/`: Click-based scriptable command surface and command output handling.
  Keep command flags thin; delegate validation and execution to task/domain layers.
- `src/ethernity/tasks/`: task state, validation, preview, execution adapters, and presentation
  models shared by the app and command runner.
- `src/ethernity/workflows/`: adapter-neutral application use cases with typed requests, issues,
  assessments, and execution results. Do not accept CLI argument models or return UI/JSON models.
- `src/ethernity/cli/features/` and `src/ethernity/cli/shared/`: feature orchestration and shared
  CLI/domain helpers. Keep planning, execution, rendering, and reporting separated.
- `src/ethernity/render/`: render contracts, layout policy, template/style parsing, and backend
  dispatch. Rendering behavior should be driven by typed inputs, geometry, and style capabilities,
  not by ad-hoc style-name checks.
- `src/ethernity/render/direct_pdf/`: direct PDF implementation details. Keep backend-specific
  drawing behind the local surface/component abstractions.
- `src/ethernity/formats/`, `src/ethernity/encoding/`, `src/ethernity/crypto/`,
  `src/ethernity/extensions/`, and `src/ethernity/qr/`: format, recovery, crypto, extension,
  and QR semantics. Do not couple these modules to UI text or display layout.
- `kit/`: browser recovery kit source and tests. Generated bundles are not source.

Anti-spaghetti rule: if a change needs behavior from another layer, add a clear typed boundary or
reuse an existing service. Do not reach across layers with string parsing, duplicated rules, or
"just this once" imports.

## Stable Coding Conventions

- Keep imports at module top level. Avoid nested runtime imports.
- Prefer explicit public exports. Do not re-export underscore helpers.
- Use `ruff format` as the only Python formatter. Do not add Black.
- Keep Python line length at 100 unless a deliberate repo-wide style change is approved.
- Prefer small named helpers over dense orchestration blocks or manual spacing tricks.
- Prefer module imports over long symbol lists when importing many names from one module.
- Use blank lines for real phase boundaries such as normalize, validate, execute, and report.
- Use `# fmt: off` / `# fmt: on` only for rare cases where structure cannot be improved.
- Keep ASCII-only edits unless a file already uses Unicode or the change clearly requires it.
- In tests, replace repeated `mock.patch(...)` stacks with fixtures, helper context managers, or
  test-support helpers.

## Generated Artifacts

- Do not edit generated artifacts directly.
- Do not edit or stage generated recovery kit bundles under
  `src/ethernity/resources/kit/recovery_kit*.bundle.html`; rebuild from `kit/` when packaging
  work requires them.
- Treat `build/`, `dist/`, `kit/dist/`, `kit/node_modules/`, cache directories, and egg-info
  directories as transient unless the user explicitly asks about them.
- Golden fixtures and visual baselines are test artifacts with compatibility value. Regenerate them
  through the relevant scripts/tests and explain why when behavior intentionally changes.

## Change Recipes

### Format Or Recovery Semantics

- Update `docs/format.md` for normative behavior.
- Update `docs/extension_publication_profile.md` for canonical extension export, carrier,
  recovery-kit, selected-recovery, minting, or compaction behavior.
- Update `docs/format_notes.md` for rationale or operational guidance.
- Update `docs/format_changes.md` only when the behavior is a compatibility-relevant delta. Before
  adding a new entry, check whether the behavior was introduced earlier on the same unreleased
  branch; if so, update that entry instead.
- Update implementation and tests in the same change. Include negative/error-path tests for parser,
  shard, recovery, or compatibility behavior.

### Rendering And Layout

- `RenderInputs` must carry explicit `doc_type`. Do not infer document type from template names and
  do not smuggle behavior through `context["doc_type"]`.
- Recovery documents must use structured `RenderInputs.recovery_meta`; do not infer recovery
  semantics by parsing display `key_lines`.
- Treat `key_lines` as display/fallback text only.
- Put style behavior toggles in style `capabilities`, parsed by
  `src/ethernity/render/template_style.py`.
- Use `RenderInputs.layout_debug_json_path` for layout diagnostics. Diagnostics must not change
  render behavior.
- Layout code should fail fast on impossible pagination or zero-capacity fallback pages rather than
  loop or silently degrade.

### CLI, Textual App, And Tasks

- `ethernity` is the human Textual app. Do not reintroduce prompt-loop UI libraries such as
  Questionary or prompt-toolkit.
- Scriptable usage lives under `ethernity run ...`; use the command registry as the current command
  list.
- Keep Textual widgets focused on editing and presenting task state. Task validation, preview, and
  execution belong in task/domain layers.
- Do not duplicate user-facing behavior in both app and command code. Share task models and
  services where possible.

### Browser Kit

- Edit source under `kit/app/`, `kit/lib/`, `kit/scripts/`, and `kit/tests/`.
- Run kit lint, format check, and tests when touching kit behavior.
- Rebuild bundles with `node build_kit.mjs` only when package/release validation requires generated
  kit resources.

### Packaging And Release

- Keep package data in `pyproject.toml` aligned with actual runtime resources.
- Keep PyInstaller and release helper scripts aligned with generated kit and template assets.
- When release artifacts change, update `docs/release_artifacts.md` if user-facing expectations
  change.

## Verification Matrix

Choose the smallest verification set that proves the change. Prefer targeted tests during
iteration, then broader gates before handoff when risk is high.

- Python lint: `uv run ruff check src tests tooling`
- Python format check: `uv run ruff format --check src tests tooling`
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
- Kit bundle rebuild: ensure `libdeflate-gzip` is on `PATH`, run `npm ci` if dependencies are
  missing, then `node build_kit.mjs` from `kit/`

## When To Update This File

Update `AGENTS.md` when a repo-wide, stable agent rule changes. Do not update it for local machine
preferences, temporary plans, exhaustive file inventories, stale command lists, or facts already
owned by source code, config, CI, or docs.

Before adding a rule, ask:

- Is it repo-wide rather than personal or task-local?
- Is it expected to remain true across branches?
- Is this the best source of truth, or should the rule live next to code/config/docs instead?
- Will it help agents avoid real mistakes without encouraging broad rewrites?

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **ethernity** (14925 symbols, 31387 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "master"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/ethernity/context` | Codebase overview, check index freshness |
| `gitnexus://repo/ethernity/clusters` | All functional areas |
| `gitnexus://repo/ethernity/processes` | All execution flows |
| `gitnexus://repo/ethernity/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
