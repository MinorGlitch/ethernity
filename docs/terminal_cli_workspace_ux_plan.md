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
- The old side summary says Required choose files.
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
- Review/result modals: write consequences, final confirmation, and execution output.
- Bottom bar: global shortcuts and one primary action.
- Modal screens: file picking, final review, and internals.

No duplicate text:

- A missing file choice should appear as an empty file selector in the workspace and as the primary
  fix action, not as three separate "Missing Files" rows.
- "Nothing will be written until final review" belongs in final review and, if needed, as a short
  workspace safety note. It should not be repeated on every screen as filler.
- "Review" should appear once as the primary action. Do not keep a second Review button in the
  workspace.

Use controls, not prose:

- Use a file picker for paths.
- Use radio choices for recovery strategy and restore target.
- Use select controls for paper/design/variant choices.
- Use switches for binary advanced options.
- Use compact selection lists for selected files and documents.
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
- `ListView`: workflow navigation with structured rows.
- `SelectionList`: selected files, selected recovery material, and multi-select options where the
  choices are known.
- `DirectoryTree`: file picker and folder browsing.
- `RadioSet` / `RadioButton`: mutually exclusive choices such as recovery method or restore
  target.
- `Select`: compact option sets such as paper size, design, kit variant, or known presets.
- `MaskedInput`: structured numeric values such as thresholds, QR density, and shard counts.
- `Switch`: binary advanced settings such as allow stale source or reveal secrets.
- `ProgressBar`: readiness only with adjacent explanatory text; not as decoration.
- `RichLog`: internals and execution logs only, never the beginner workspace.
- `MarkdownViewer`: help, review, and result summaries.
- `TabbedContent`: dense settings and internals subviews.
- `Collapsible`: advanced sections and secondary result details.
- `LoadingIndicator`: mounted only while long-running work is actually running.

Do not use `OptionList` or generic checklist renderers for primary workspaces.

## Shell Layout Contract

The shell keeps a stable task-rail plus workspace shape. The old right summary rail is intentionally
absent; consequences live in the focused workspace, review modal, result modal, and internals modal.

```text
Header
Task rail | Task-specific workspace
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

### Bottom Bar

The bottom bar shows global navigation and the one primary action. It should not duplicate the
workspace.

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
  [selected paths list or empty state]
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

Review/result summary:

- Documents to create: main backup document, recovery guide, recovery documents, kit index if
  supported.
- Recovery rule: any 2 of 3, single phrase, or custom.
- Output target.
- Blockers: choose files, choose output.

Remove from this workspace:

- The generic section checklist.
- The separate next-action strip.
- The duplicate Review button.
- Repeated "Missing Files" lines.

### Restore Files

Goal: identify a backup source, unlock it, choose target version, choose output.

Workspace structure:

```text
Restore files

Backup source
  [source list or empty state]
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

Review/result summary:

- Restore target.
- Output path.
- Expected recovered file count when known.
- Authentication/signature warning when relevant.
- Blockers: source, unlock, output, target only when missing.

Use a compact list for detected backup contents once source parsing exists. Until then, show a
concise source list, not empty space.

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
  [selected paths list]
  Add files  Add folder  Remove selected

Unlock
  Recovery method controls

Update options
  Recovery documents [reuse / recreate]
  Print layout [A4] [sentinel]
```

Review/result summary:

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
  [source summary list]

Unlock
  Passphrase or recovery documents

Rebuild output
  Output folder [path field] [Choose]
  Paper/design controls
```

Review/result summary:

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

Review/result summary:

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

Review/result summary:

- Kit variant.
- Paper/design.
- Output PDF.

### Settings

Settings can keep the current direction, with these refinements:

- Keep grouped categories.
- Keep direct controls.
- Keep advanced settings visible but not noisy.
- Remove generic task title/explainer copy.
- Settings shows config file target, unsaved changes, and validation errors inline.

## Copy Ownership Rules

Use this table when implementing. If a sentence does not have an owner, delete it.

| Information | Owner |
| --- | --- |
| Selected files/folders | Center workspace selection list |
| Missing selected files/folders | Empty state inside selection list plus primary fix action |
| Recovery threshold | Center recovery controls and final review |
| Output path | Center output field, final review, and result modal |
| Documents to create | Final review and result modal |
| "Nothing written until review" | Final review modal; optional one-line workspace safety note |
| Keyboard shortcuts | Footer and help modal only |
| Debug/internal backup payload | Internals modal only |
| Execution result paths | Result modal after execution |

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
- Selection lists support row focus without pretending empty states are selected rows.
- File rows expose clear/remove actions through keyboard and mouse.

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
  summary
  blockers
  primary_action
  diagnostics_available
```

Workspace groups should be typed:

- path picker group
- selected paths list
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
- Add tests that enforce copy ownership: no duplicate blocker strings across visible regions.
- Add viewport tests for at least wide desktop, medium terminal, and narrow terminal.

### Phase 2: Replace The Generic Workspace Router

- Replace the single generic section list with a `ContentSwitcher`.
- Add one workspace widget per task.
- Keep the existing task state and execution flow while replacing only presentation.
- Keep Settings as its own workspace.

### Phase 3: Create Backup Vertical Slice

- Build the backup workspace completely first.
- Replace section list with selected-files list, recovery controls, output control, and layout
  controls.
- Move documents-to-create into review/result surfaces.
- Remove duplicate Review surfaces.
- Verify file picker, passphrase/recovery editing, output picker, final review, and internals.

### Phase 4: Restore Vertical Slice

- Build source, unlock, target, and output groups.
- Make the unlock method explicit instead of hidden behind a text edit.
- Add source summary and output consequences to the workspace and review/result surfaces.
- Verify restore review and execution still use the same task state.

### Phase 5: Maintenance Tasks

- Build Add files, Rebuild backup, Replace recovery docs, and Recovery kit.
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
- The same blocker sentence does not appear multiple times in visible workflow chrome.
- The old side summary rail is absent; review/result modals carry consequences and execution
  details.
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
