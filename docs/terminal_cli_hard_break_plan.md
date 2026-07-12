# Terminal CLI Hard Break Plan

## Decision

Rebuild the human-facing Ethernity terminal experience from the ground up.

This is not an incremental cleanup of the current interactive CLI. The new
implementation removes the prompt-driven wizard/workspace model, removes old
command vocabulary, and introduces a real terminal application backed by shared
task state and validation.

The product remains terminal-first.

## Goals

- Make Ethernity usable by non-power users without exposing internal domain nouns first.
- Keep task context visible at all times: what is complete, what is missing, what will be
  created, what is risky, and whether anything has been written.
- Replace question-by-question flows with task workspaces.
- Use one shared task engine for the Textual app and scriptable command runner.
- Make every write action pass through an explicit preview and final review.
- Keep automation/script usage available without making it the primary human experience.

## Non-Goals

- No compatibility shims for old interactive commands.
- No hidden or deprecated old command aliases.
- No prompt-library fallback for the human UI.
- No browser UI.
- No rewrite of crypto, encoding, rendering, or recovery algorithms as part of the UI break.
- No user-facing exposure of expert terms in beginner flows unless the user opens advanced
  details.

## Current Problems To Remove

The current CLI exposes too much implementation vocabulary and too many parallel command
paths. Top-level help currently mixes beginner and power commands, including paired names
for the same conceptual task.

Examples of surfaces to remove or replace:

- `create` and `backup`
- `restore` and `recover`
- `add` and `extend`
- `rebuild` and `compact`
- `reprint-shards` and `mint`
- prompt-loop workspaces
- `wizard_flow`, `wizard_stage`, and `wizard_substep` as the primary UX model
- direct Questionary and prompt-toolkit based controls

Beginner flows should not lead with terms such as:

- `mint`
- `compact`
- `extend`
- `fallback`
- `payloads`
- `auth frames`
- `signing seed`
- `extension doc hash`
- `QR chunk size`
- `shard threshold`

Those concepts may still exist in task internals, advanced panes, debug output, API schemas,
or format documentation.

## Final Library Stack

Use:

- Textual: primary full-screen terminal application.
- Rich: output formatting, summaries, tables, progress, logs, tracebacks.
- Click: scriptable command runner.
- Pydantic: task state models, validation boundaries, JSON/schema serialization.
- platformdirs: config, cache, and data paths.

Remove from the new CLI/UI layer:

- Typer
- Questionary
- direct prompt-toolkit app code
- custom prompt controls
- current guided workspace prompt-loop framework

Do not add:

- InquirerPy
- curses
- urwid
- argparse
- mixed Click and Typer command routing
- prompt fallback layer for the Textual app

## New Public Surface

Plain `ethernity` launches the human terminal application.

Scriptable usage lives under `ethernity run`.

```text
ethernity
ethernity run backup
ethernity run restore
ethernity run add-files
ethernity run rebuild
ethernity run replace-recovery-docs
ethernity run print-kit
```

The old `ethernity api` command group is removed. Machine-readable output is folded into
`ethernity run ... --json` so there is one scriptable task surface.

## Product Language

Primary human actions:

- Create a backup
- Restore files
- Work on an existing backup
- Print a recovery kit
- Settings

Maintenance actions:

- Add files to a backup
- Rebuild a backup
- Replace recovery documents
- Print another recovery kit

Avoid making the user choose between implementation nouns. The UI should ask about their
real-world situation:

- "I have printed documents or scans"
- "I have a generated backup folder"
- "I have the passphrase"
- "I have recovery documents"
- "I want the latest backup"
- "I want only the original backup"

## Target Architecture

```text
src/ethernity/app/
  main.py
  theme.tcss
  screens/
    home.py
    backup.py
    restore.py
    maintain.py
    kit.py
    settings.py
  widgets/
    action_bar.py
    section_list.py
    task_shell.py
    preview_panel.py
    file_picker.py
    review_table.py
    warning_callout.py

src/ethernity/tasks/
  models.py
  backup.py
  restore.py
  add_files.py
  rebuild.py
  replace_recovery_docs.py
  print_kit.py

src/ethernity/run/
  cli.py
  output.py
  json_io.py
```

Ownership boundaries:

- `ethernity.app`: Textual screens and widgets only.
- `ethernity.tasks`: task state, validation, preview, planning, and execution adapters.
- `ethernity.run`: Click command definitions and scriptable output.
- existing domain modules: crypto, framing, sharding, rendering, scanning, config, and
  persistence.

## Task Contract

Every user task should expose the same shape:

```text
state
sections()
validate_task()
preview()
execute()
recoverable_errors()
```

The Textual app edits task state and renders task status. It does not own domain logic.

The Click runner maps flags into task state, validates, previews when requested, and
executes.

The API, if retained, serializes task state, validation results, preview results, and
execution events.

## Suggested Task Models

Core models:

- `TaskSection`
- `TaskIssue`
- `TaskPreview`
- `TaskAction`
- `TaskExecutionPlan`
- `TaskExecutionResult`

Backup:

- `BackupTaskState`
- `BackupSourceSelection`
- `BackupPassphrasePolicy`
- `BackupRecoveryPolicy`
- `BackupOutputSelection`
- `BackupPrintLayout`

Restore:

- `RestoreTaskState`
- `RestoreSourceSelection`
- `RestoreUnlockSelection`
- `RestoreTargetSelection`
- `RestoreOutputSelection`

Maintenance:

- `AddFilesTaskState`
- `RebuildTaskState`
- `ReplaceRecoveryDocsTaskState`

Pydantic should validate UI and command state. Existing internal dataclasses and domain
models can remain where they are already well suited.

## Textual App Design

The app should feel like a calm archival/security workstation:

- restrained charcoal or warm light theme
- high contrast text
- teal focus accent
- green ready state
- amber missing/warning state
- red destructive/error state
- thin borders
- dense but readable spacing
- no decorative gradients
- no terminal "hacker" styling
- no nested panel clutter

Primary layout:

```text
Header
Left navigation
Main task workspace
Right preview/consequences panel
Bottom action bar
```

The user should always see:

- current task
- required sections
- ready/missing/warning state
- next recommended action
- write consequences
- final action availability

Internals should be available on demand without disturbing the beginner flow. Use a
secondary Internals action, not inline debug noise. The internals view should use native
Textual widgets such as `RichLog` for structured internals and `Switch` for local reveal controls.
Sensitive values must be redacted by default and revealed only after an explicit in-view toggle.

For backup creation, Internals is the modern replacement for the old pre-encryption debug
dump. It should expose payload, envelope, manifest, z-base-32 previews, signing-key state, and
sharding facts in a structured modal instead of pushing raw debug text into the main workspace.

## Screen Map

Home:

- Create a backup
- Restore files
- Work on an existing backup
- Print a recovery kit
- Settings

Create backup:

- Files
- Recovery method
- Output
- Print layout
- Preview documents to create
- Final review and create

Restore files:

- Backup source
- Unlock method
- Restore target
- Output
- Preview recovered files
- Final review and restore

Work on existing backup:

- Add files to a backup
- Rebuild a backup
- Replace recovery documents

Recovery kit:

- Print recovery kit
- Choose paper/layout
- Final review and render

Doctor:

- Python/runtime status
- Direct PDF rendering status
- QR scanning support
- write permissions
- template/resource integrity

Settings:

- paper size
- template design
- default output folder
- recovery defaults
- advanced rendering settings

## Interaction Rules

Suggested global keys:

- `Tab`: move focus
- `Shift+Tab`: move focus backward
- Arrow keys: move between visible tasks or focus regions
- `h`/`j`/`k`/`l`: terminal-native navigation between task rail and workspace
- `Enter`: select or edit
- `Esc`: back or close modal
- `/`: search/filter where applicable
- `?`: help overlay
- `Ctrl+R`: review
- `Ctrl+Enter`: execute final action when available

Rules:

- Never write files before final review.
- Show exact output paths before writing.
- Show exact document counts before writing.
- Show stale/trust warnings in the task surface, not only after failure.
- Prefer editing a visible section over asking serial questions.
- Keep advanced fields collapsed by default.
- Keep dangerous/debug fields out of beginner flows.

## Click Runner Design

`ethernity run` should be explicit and boring. It is for scripts and power users.

Examples:

```text
ethernity run backup --input secrets.txt --output-dir backup-out
ethernity run restore --scan scans --output recovered
ethernity run add-files --backup-folder backup-out --input new-file.txt
ethernity run rebuild --scan scans --output-dir rebuilt
ethernity run replace-recovery-docs --scan scans --output-dir replacement-docs
ethernity run print-kit --output recovery-kit.pdf
```

Runner behavior:

- maps flags into Pydantic task state
- validates task state
- prints clear Rich summaries
- supports `--json` for machine output where needed
- supports `--yes` only when all required state is provided
- returns stable exit codes

## Migration Plan

This is a hard break, so migration here means implementation sequencing, not compatibility.

### Phase 1: Foundation

- Add Textual and Pydantic dependencies.
- Create `ethernity.tasks` package.
- Define shared task result models.
- Build `BackupTaskState` and `RestoreTaskState`.
- Add tests for task validation and preview behavior.

### Phase 2: Textual Shell

- Create `ethernity.app`.
- Build the app shell, navigation, task screen layout, and theme.
- Implement home screen.
- Implement reusable widgets:
  - section list
  - preview panel
  - action bar
  - warning callout
  - review table

### Phase 3: Backup Task

- Port create-backup flow into `BackupTaskState`.
- Connect Textual backup screen to task state.
- Connect preview to existing backup planning/rendering logic.
- Add final review and execute.
- Add Textual tests for the backup screen.

### Phase 4: Click Runner

- Create `ethernity.run.cli`.
- Implement `ethernity run backup`.
- Use the same backup task model.
- Add runner tests for validation, preview, execution planning, and exit codes.

### Phase 5: Restore Task

- Port restore flow into `RestoreTaskState`.
- Connect Textual restore screen.
- Implement preview-before-write.
- Implement `ethernity run restore`.
- Add tests for scan/text/passphrase/recovery-document paths.

### Phase 6: Maintenance Tasks

- Implement add-files task.
- Implement rebuild task.
- Implement replace-recovery-docs task.
- Implement print-kit task.
- Add corresponding Textual screens and Click runner commands.

### Phase 7: Settings

- Implement settings screen.
- Persist settings through existing config infrastructure.

Checkpoint:

- Settings uses a normal grouped form, not a task checklist, category browser, or table.
- User-facing settings are backed by the config API surface and rendered as direct Textual
  controls: selects for option sets, inputs for numeric values, switches for booleans, and the
  shared file picker for path settings.
- Settings hides task-readiness filler such as progress, "next best move", and explanatory
  workspace copy. The preview pane only shows the save target and real validation issues.

### Phase 8: Remove Old CLI

- Delete Typer bootstrap and feature command modules.
- Delete Questionary and prompt-toolkit UI modules.
- Delete old workspace prompt-loop modules.
- Remove Typer, Questionary, and prompt-toolkit dependencies if no longer needed transitively.
- Update package entry point to launch the new Textual app.
- Update tests and documentation.

## Test Strategy

Task tests:

- state defaults
- validation for missing fields
- validation for invalid combinations
- preview document counts
- output path behavior
- recoverable error classification

Textual tests:

- app starts
- navigation works
- sections update after edits
- final action disabled until ready
- warnings render for risky states
- review screen lists exact outputs

Click runner tests:

- required options
- happy paths
- JSON output
- exit codes
- `--yes` behavior

Regression tests:

- backup artifacts still render
- restore still decrypts known fixtures
- recovery document and shard behavior remains format-compatible
- API, if retained, emits stable machine-readable events

## Implementation Checkpoint

The first implementation slice has started on this branch:

- `ethernity` now routes through the new terminal entry point.
- `ethernity run` is backed by Click, not the old top-level Typer command tree.
- Textual, Rich, Click, and Pydantic are wired into the new layer.
- `BackupTaskState` and `RestoreTaskState` expose shared validation, preview, planning, and
  execution adapters.
- The Textual shell can switch between backup, restore, recovery kit, and settings tasks, edit
  task fields where implemented, show final review, and execute ready tasks through shared task
  state.
- The center task area, left navigation, and right preview rail are Textual widgets rather than
  static text dumps.
- The center task renderer has been split into reusable Textual widgets for section lists,
  settings forms, and task action bars, so future task-specific screens do not have to keep
  extending one generic workspace blob.
- The settings workspace now removes the redundant hero/explainer copy, starts directly on
  editable controls, and uses a compact `Save` action instead of a full-width review slab.
- The task canvas now uses an explicit grid so the central workspace keeps real height across
  backup and settings views; regression coverage checks widget regions instead of only checking
  whether widgets are technically mounted.
- Primary task buttons and preview buttons have been made compact controls instead of full-width
  slabs.
- Navigation now supports number shortcuts, `j`/`k`, arrow-key movement, and `h`/`l` focus
  movement between task navigation and the workspace.
- The footer is intentionally sparse; visible buttons and the help overlay carry secondary
  actions instead of forcing every shortcut into the bottom bar.
- Internals are exposed as an on-demand secondary view; backup internals now adapt the old
  pre-encryption internals dump into payload, envelope, manifest, z-base-32, signing-key, and
  secret-material blocks with sensitive values redacted by default.
- `ethernity run backup`, `ethernity run restore`, `ethernity run add-files`,
  `ethernity run rebuild`, `ethernity run replace-recovery-docs`, and
  `ethernity run print-kit` can preview and execute through the same task models.
- The new Click runner has real integration coverage for a backup/restore round trip: it
  renders backup PDFs through `ethernity run backup`, restores from the generated backup folder
  through `ethernity run restore`, and verifies the recovered file contents.
- The Textual app has real integration coverage for the same write path through final review:
  it executes backup creation from the app, executes restore from the generated backup folder
  from the app, and verifies the recovered file contents.
- `ethernity run ... --json` emits one machine-readable JSON object backed by the same task
  validation, preview, execution plan, and result models used by Rich output.
- JSON runner errors for not-ready and confirmation-required states are emitted as JSON payloads
  with stable non-zero exit codes instead of mixed Rich/Click text.
- Typer, Questionary, and prompt-toolkit have been removed from runtime package dependencies.
  They have also been removed from the dev extra, lock file, and Homebrew tap resource list.
- The new app/run/tasks layer is guarded against old interactive CLI imports: tests fail if it
  imports Typer, Questionary, prompt-toolkit, old command modules, old prompt UI modules,
  `ui_api`, or recovery prompt loops.
- The legacy `ethernity.cli` package barrel no longer exposes the old Typer app, old bootstrap
  `main`, root `main` handoff, or old interactive wizard aliases. The package remains only as the
  home for non-interactive service modules.
- The legacy `ethernity.cli` package barrel no longer exports old command-runner functions
  (`run_backup`, `run_backup_command`, `run_recover_command`, `run_compact`, `run_extend`, or
  `run_mint_command`). Tests and internal callers now import those directly from their owning
  modules while that old code is being retired.
- The legacy `ethernity.cli` package barrel has been reduced to a package marker only. It no
  longer re-exports old shared constants, data types, crypto helpers, command runners, or entry
  points.
- The old `ethernity.cli.bootstrap` root dispatch package has been removed; `src/ethernity/main.py`
  now owns root help/version, no-args terminal launch, and `ethernity run` dispatch directly.
- The `python -m ethernity.cli` compatibility entrypoint has been removed; `python -m ethernity`
  is the supported module entrypoint.
- New app/run/task package roots, plus the app `screens`, app `widgets`, and run `commands`
  package roots, are package markers only. They do not re-export moved symbols; callers import
  from the owning modules directly.
- Questionary and prompt-toolkit source modules have been removed from the shared CLI UI package,
  and those prompt libraries have been removed from the dev dependency extra and lock file.
- The old Typer bootstrap, Typer feature command modules, prompt-loop workspaces, guided wizard
  modules, shared recovery prompt module, and first-run prompt onboarding surface have been
  deleted. Typer has also been removed from the dev dependency extra and lock file.
- The remaining Rich CLI UI package is now limited to non-interactive output helpers such as
  console, progress/status, tables, panels, and completion summaries. It no longer exposes
  wizard flow, wizard stage, wizard substep, picker, or prompt helpers.
- The old `ethernity api` command group and unused NDJSON API handler modules have been removed.
  The schema/docs for that retired surface were deleted, the CI schema validation job was removed,
  and `check-jsonschema` was dropped from the dev dependency extra and lock file.
- Integration and e2e backup/recovery tests that still mattered now call the new task/service
  layer or `ethernity run`; old Typer/API/prompt unit tests were deleted instead of shimmed.
- The runner now has a global `ethernity run --config PATH` option so protocol fixtures and
  scripted recovery drills can use explicit configuration without reviving the old root command
  tree.
- The old advanced recovery/mint/compact subprocess coverage has been retargeted to the new
  task names and user-facing option language: restore payloads use
  `--recovery-payloads-file`, replacement recovery documents use
  `replace-recovery-docs`, rebuilding uses `rebuild`, and extension updates use `add-files`.
- `README_PYPI.md`, frozen fixture builders, baseline e2e tests, and the Homebrew tap formula
  were updated to the new public command surface.
- The task canvas now keeps checklist/settings wrappers stretched to the available workspace and
  has regression coverage for returning from Settings to Add files without leaving the old
  settings action/content visible.
- The task canvas now has a compact next-action strip that shows the first blocking section and
  opens the matching editor or file picker without adding explanatory copy to the workspace.
- Release-note copy for the public hard-break surface lives in
  `docs/terminal_cli_hard_break_release_notes.md`.

Post-release follow-up:

- Keep simplifying individual Textual task workspaces after hands-on review. The shared task
  canvas is now acceptable for the hard break because the common pieces are real widgets, the
  settings view is a dedicated form, and the next-action strip gives task-specific direction
  without explanatory filler.
- The next UX pass is specified in `docs/terminal_cli_workspace_ux_plan.md`. It replaces the
  generic non-settings checklist workspaces with task-specific editors, defines ownership for
  workspace/outcome/blocker copy, and removes duplicated preview/needs-attention text.
- Review the release-note draft before publishing it externally.

## Documentation To Update

- No in-repo packaging or release docs with old top-level commands were found in the final cleanup
  search. The release-note draft is now in-repo; external wiki/release publishing still needs a
  final editorial pass.

## Completion Evidence

- `uv run ruff check src tests`
- `uv run ruff format --check src tests`
- `uv run pyrefly check`
- `uv run pytest tests/unit tests/integration tests/e2e -q`
  - Result: `1577 passed, 4 skipped`.
- `python -m ethernity --help` shows only the terminal app entry point and `run` group.
- `python -m ethernity run --help` shows the scriptable task commands:
  `backup`, `restore`, `add-files`, `rebuild`, `replace-recovery-docs`, and `print-kit`.
- Final source/dependency search found no Typer, Questionary, or prompt-toolkit imports in
  production code and no stale top-level command examples outside intentional removal notes.

## Acceptance Criteria

- Running `ethernity` opens the new Textual app.
- The app can create a backup end to end.
- The app can restore a backup end to end.
- `ethernity run backup` and `ethernity run restore` work without Textual.
- Old prompt-driven interactive code is removed.
- Typer and Questionary are gone from direct project dependencies.
- Beginner-facing UI does not expose old internal nouns as primary choices.
- Every write action has preview and final review.
- Existing crypto, rendering, and recovery tests still pass.

## Decisions Closed

- Textual browser mode is not a supported product surface for this hard break. Ethernity remains
  terminal-first.
- The default theme is the restrained dark terminal theme in `src/ethernity/app/theme.tcss`.
  Light-theme support can be designed later, but it is not part of this break.
- Settings is global-first. Task-scoped choices stay inside their task workspace; persistent
  defaults live in the Settings form.
