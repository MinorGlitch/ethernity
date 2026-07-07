# Terminal CLI Workspace UX Plan

## Reader And Action

Reader: an Ethernity engineer redesigning the Textual terminal app after the hard-break CLI
rewrite.

After reading this plan, the engineer should be able to replace the generic non-settings
workspaces with task-specific, beginner-friendly workspaces that do not repeat the same status,
preview, and blocker text in multiple regions.

## Problem To Solve

The current terminal shell is structurally better than the old prompt loop, but the main workspaces
are still not proper interfaces. Most non-settings tasks render as a checklist. The screenshot of
Create backup shows the same idea repeated in several places:

- The center workspace says Files is missing.
- The next-action strip says Files is missing.
- The checklist says Files is missing.
- The right rail says Required choose files.
- The bottom bar also offers Choose files.
- Preview and Needs attention compete with the main workspace instead of helping it.

This makes the app feel busy while still being empty. It is especially bad for non-power users:
they are asked to interpret status text instead of manipulating clear controls.

## UX Direction

The new interface should be a task workstation, not a checklist.

Each task workspace gets purpose-built controls for the thing the user is doing. A backup workspace
should look like a backup setup form. A restore workspace should look like a restore setup form.
An add-files workspace should look like an update editor. The shared shell remains, but the center
is no longer shared generic content.

The settings workspace is the nearest correct direction: it is direct, compact, grouped, and uses
real controls. The other workspaces should reach that level of specificity without copying the
settings layout exactly.

## Design Principles

One region owns one job:

- Left rail: task navigation and task-level readiness only.
- Center workspace: inputs and decisions the user can change now.
- Right rail: outcome, write consequences, and blockers that are not already visible as controls.
- Bottom bar: global shortcuts and one primary action.
- Modal screens: file picking, final review, and internals.

No duplicate text:

- A missing file choice should appear as an empty file selector in the workspace and as one blocker
  in the right rail, not as three separate "Missing Files" rows.
- "Nothing will be written until final review" belongs in final review and, if needed, as a short
  right-rail safety note. It should not be repeated on every screen as filler.
- "Review" should appear once as the primary action. Do not keep a second Review button in the
  right rail unless the bottom action bar is hidden at a narrow width.

Use controls, not prose:

- Use a file picker for paths.
- Use radio choices for recovery strategy and restore target.
- Use select controls for paper/design/variant choices.
- Use switches for binary advanced options.
- Use tables or compact lists for selected files and documents.
- Use collapsible details for advanced controls.

Use empty states that are actions:

- "No files selected" should sit inside a file-selection area with an Add files action.
- "No output selected" should sit inside an output field with a Choose output action.
- Avoid paragraphs explaining what the task is. The task name and controls should carry the
  interface.

## Textual Widgets To Lean On

Stay with Textual. Do not add another TUI framework.

Use these Textual widgets deliberately:

- `ContentSwitcher`: switch between task-specific center workspaces without leaving old content
  mounted or visible.
- `DataTable`: selected files, output documents, setup checks, and recovery document sets.
- `SelectionList`: multi-select options where the choices are known.
- `DirectoryTree`: file picker and folder browsing.
- `Tree`: detected backup contents, update chains, and document groups.
- `RadioSet` / `RadioButton`: mutually exclusive choices such as recovery method or restore
  target.
- `Select`: compact option sets such as paper size, design, kit variant, or known presets.
- `Input`: short explicit values such as thresholds, document hashes, or save names.
- `Switch`: binary advanced settings such as allow stale source or reveal secrets.
- `ProgressBar`: readiness only where progress is meaningful; not as decoration.
- `RichLog`: internals and execution logs only, never the beginner workspace.
- `TabbedContent`: advanced subviews only when one task genuinely has separate modes.

Keep `OptionList` for the left rail and small command menus. Do not use it as the main workspace
for every task.

## Shell Layout Contract

The shell keeps a stable three-column shape, but changes what each column owns.

```text
Header
Task rail | Task-specific workspace | Outcome rail
Footer shortcuts
```

### Left Task Rail

Keep the rail compact, but make it more informative:

- Group tasks as Backup, Restore, Maintain, Tools.
- Show a small readiness marker per task: empty, partial, ready, or attention.
- Do not show detailed blockers here.
- Keep number shortcuts and hjkl/arrows.

### Center Workspace

The center column owns editing. It should have:

- A short task title.
- A compact readiness count.
- Direct controls grouped by user intent.
- A single inline blocker banner only when the next action is not obvious from the focused control.
- No preview list.
- No "documents to create" copy.
- No repeated "needs attention" list.

### Right Outcome Rail

Rename the mental model from Preview to Outcome.

The rail shows:

- What will be written or read.
- The output target.
- Document/file counts.
- Security-sensitive consequences.
- Current blockers only if they are not already visible in the focused workspace group.
- Last execution result.

When there are no blockers, do not show "No blockers" as a permanent block. Hide the section or
show a single muted Ready line near the primary action.

### Bottom Bar

The bottom bar shows global navigation and the one primary action. It should not duplicate the
right rail.

Primary action rules:

- If not ready: primary action is disabled and labels the missing next step, or the next-step
  button is shown in the relevant workspace group.
- If ready: primary action is Review backup, Review restore, Add files, Rebuild, Create kit, or
  Save settings.
- Final write still happens only from the review modal.

## Workspace Designs

### Create Backup

Goal: choose protected content, recovery strategy, output, and print layout.

Workspace structure:

```text
Create backup                                      2/4 ready

Files to protect
  [selected paths table or empty state]
  Add files  Add folder  Remove selected

Recovery
  (o) Recommended: any 2 of 3 recovery documents
  ( ) Single recovery phrase
  ( ) Custom shards: threshold [2] of [3]
  Advanced: signing key mode, signing key shards

Destination and print
  Output folder  [path field] [Choose]
  Paper          [A4 v]
  Design         [sentinel v]
```

Outcome rail:

- Documents to create: main backup document, recovery guide, recovery documents, kit index if
  supported.
- Recovery rule: any 2 of 3, single phrase, or custom.
- Output target.
- Blockers: choose files, choose output.

Remove from this workspace:

- The generic section checklist.
- The separate next-action strip.
- The duplicate Review button in the right rail.
- Repeated "Missing Files" lines.

### Restore Files

Goal: identify a backup source, unlock it, choose target version, choose output.

Workspace structure:

```text
Restore files

Backup source
  [source table or empty state]
  Choose scans  Choose recovery text  Choose payload file

Unlock
  (o) Passphrase
  ( ) Recovery documents
  ( ) Recovery payload files
  [contextual control for selected unlock method]

Restore target
  (o) Latest supplied backup
  ( ) Original backup only
  ( ) Specific update [index/hash field]

Output
  Restore into [path field] [Choose]
```

Outcome rail:

- Restore target.
- Output path.
- Expected recovered file count when known.
- Authentication/signature warning when relevant.
- Blockers: source, unlock, output, target only when missing.

Use a `Tree` for detected backup contents once source parsing exists. Until then, show a concise
source table, not empty space.

### Add Files To Backup

Goal: update an existing backup folder with new protected files.

Workspace structure:

```text
Add files

Backup to update
  Backup folder [path field] [Choose]
  Current source [use folder] [choose scans]
  Source freshness [verified / needs confirmation]

Files to add
  [selected paths table]
  Add files  Add folder  Remove selected

Unlock
  Recovery method controls

Update options
  Recovery documents [reuse / recreate]
  Print layout [A4] [sentinel]
```

Outcome rail:

- Backup folder being updated.
- New update documents to write.
- Source freshness and stale-source risk.
- Blockers: backup folder, files to add, unlock, freshness confirmation.

### Rebuild Backup

Goal: reconstruct printable documents from an existing backup source.

Workspace structure:

```text
Rebuild backup

Source
  Choose backup folder or scans
  [source summary table]

Unlock
  Passphrase or recovery documents

Rebuild output
  Output folder [path field] [Choose]
  Paper/design controls
```

Outcome rail:

- Documents that will be rebuilt.
- Output target.
- Any trust or stale-source notes.

### Replace Recovery Documents

Goal: create a new recovery set for an existing backup.

Workspace structure:

```text
Replace recovery docs

Backup source
  [source selector]

Unlock
  [unlock controls]

New recovery set
  (o) Recommended any 2 of 3
  ( ) Custom threshold [2] of [3]
  Signing key recovery [off/on] threshold controls

Output
  Output folder [path field] [Choose]
```

Outcome rail:

- New recovery document count.
- Threshold rule.
- Whether signing-key recovery docs are included.
- Output target.

### Recovery Kit

Goal: render a printable recovery kit.

Workspace structure:

```text
Recovery kit

Print
  Variant [lean/scanner]
  Paper [A4]
  Design [sentinel]

Output
  Output PDF [path field] [Choose]
```

Outcome rail:

- Kit variant.
- Paper/design.
- Output PDF.

### Setup Check

Goal: show environment health and actionable failures.

Workspace structure:

```text
Setup check

[DataTable]
Check                 Status      Fix
Python runtime        Ready       -
Config file           Ready       Open settings
Render backend        Warning     Show details
Kit assets            Ready       -

Details for selected check
  [RichLog or Static details]
```

Outcome rail:

- Overall status.
- Required fixes.
- Optional diagnostics action.

### Settings

Settings can keep the current direction, with these refinements:

- Keep grouped categories.
- Keep direct controls.
- Keep advanced settings visible but not noisy.
- Remove generic task title/explainer copy.
- Outcome rail only shows config file target, unsaved changes, and validation errors.

## Copy Ownership Rules

Use this table when implementing. If a sentence does not have an owner, delete it.

| Information | Owner |
| --- | --- |
| Selected files/folders | Center workspace file table |
| Missing selected files/folders | Empty state inside file table plus one right-rail blocker |
| Recovery threshold | Center recovery controls and right-rail outcome |
| Output path | Center output field and right-rail outcome |
| Documents to create | Right outcome rail only |
| "Nothing written until review" | Final review modal; optional one-line safety note in outcome rail |
| Keyboard shortcuts | Footer and help modal only |
| Debug/internal backup payload | Internals modal only |
| Execution result paths | Right outcome rail after execution |

## Interaction Model

Navigation:

- `j` / Down: next focusable item in the active region.
- `k` / Up: previous focusable item in the active region.
- `h` / Left: move to task rail or previous region.
- `l` / Right: move to workspace or next region.
- Tab and Shift+Tab keep standard focus traversal.
- Enter activates focused controls.
- Space toggles radio/switch/list selections.
- `?` opens help.
- `Ctrl+R` opens final review only when ready; otherwise it focuses the first blocker.

Mouse:

- Every visible button is clickable.
- Tables support row selection.
- File rows expose remove actions through keyboard and mouse.

Focus:

- Focus must never land on hidden controls.
- Leaving Settings and returning to another task must reset focus to that task workspace, not to a
  stale settings control.
- Modals must open centered and return focus to the invoking control.

## Presentation Model Changes

The current task state models expose sections, validation, preview, and execution. That was enough
to make the hard break work, but it is too thin for proper workspaces.

Add a presentation layer above task state:

```text
TaskPresentation
  task_key
  title
  readiness
  workspace_groups
  outcome_items
  blockers
  primary_action
  diagnostics_available
```

Workspace groups should be typed:

- path picker group
- selected paths table
- radio choice group
- option select group
- numeric threshold group
- output target group
- advanced collapsible group
- details/log group

This presentation layer should be computed from each task state. The Textual widgets render
presentation objects; they should not infer task semantics from preview strings.

## Implementation Phases

### Phase 1: Lock The UX Contract

- Add a small presentation model.
- Add tests that assert non-settings tasks produce task-specific groups, not only generic sections.
- Add tests that enforce copy ownership: no duplicate blocker strings across center and right rail.
- Add viewport tests for at least wide desktop, medium terminal, and narrow terminal.

### Phase 2: Replace The Generic Workspace Router

- Replace the single generic section list with a `ContentSwitcher`.
- Add one workspace widget per task.
- Keep the existing task state and execution flow while replacing only presentation.
- Keep Settings as its own workspace.

### Phase 3: Create Backup Vertical Slice

- Build the backup workspace completely first.
- Replace section list with selected-files table, recovery controls, output control, and layout
  controls.
- Move documents-to-create entirely to the right rail.
- Remove duplicate Review in the right rail.
- Verify file picker, passphrase/recovery editing, output picker, final review, and internals.

### Phase 4: Restore Vertical Slice

- Build source, unlock, target, and output groups.
- Make the unlock method explicit instead of hidden behind a text edit.
- Add source summary and output consequences to the right rail.
- Verify restore review and execution still use the same task state.

### Phase 5: Maintenance Tasks

- Build Add files, Rebuild backup, Replace recovery docs, Recovery kit, and Setup check.
- Use shared typed group widgets, not shared prose.
- Keep task-specific language and controls in each workspace.

### Phase 6: Polish And Regression

- Tune density at common terminal sizes.
- Ensure palette variables still drive all app colors.
- Check that no text overlaps, truncates badly, or floats in empty space.
- Keep diagnostics hidden behind the Internals action.
- Update release notes after screenshots are acceptable.

## Acceptance Criteria

- Non-settings task workspaces no longer render as a generic checklist.
- Every non-settings task has direct controls that match the task.
- The same blocker sentence does not appear in the center workspace and the right rail at the same
  time.
- The right rail shows outcome and blockers only; it does not duplicate editable controls.
- The primary write/review action appears once in the normal layout.
- File, folder, and output choices use the proper file picker.
- Internals remain on demand and redacted by default.
- Arrow keys and hjkl navigation work across rail, workspace, tables, and controls.
- At common terminal sizes, text does not overlap and controls do not float in large empty areas.
- Textual theme/palette changes continue to affect the app.

## Verification Plan

Run these after implementation:

- Unit tests for task presentation objects.
- Textual pilot tests for each workspace.
- Textual pilot tests for focus movement and modal return focus.
- Screenshot/manual review at wide, medium, and narrow terminal sizes.
- Existing terminal app integration tests.
- Ruff, format check, Pyrefly, and the relevant unit/integration/e2e test set.

## References

- Textual widget gallery: https://textual.textualize.io/widget_gallery/
- Textual TextArea reference: https://textual.textualize.io/widgets/text_area/
