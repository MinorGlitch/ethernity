# TUI Presentation Redesign Plan

## Reader And Outcome

Reader: an Ethernity engineer redesigning the Textual application without changing backup,
recovery, format, or cryptographic behavior.

Outcome: the TUI should feel like a calm, precise desktop application adapted to the terminal,
not a validation model rendered as a long form. Every workflow must make the current decision,
the next action, and the write consequence obvious at 160x48, 120x32, and 80x24.

This plan supersedes the presentation-level portions of
`docs/terminal_cli_workspace_ux_plan.md`. That plan established the correct architectural move to
task-specific workspaces. The current implementation has made that move, but the result still
needs a product-design pass.

## Implementation Status

Completed on 2026-07-11. The current-state audit below is retained as the pre-redesign baseline.

- Restore, Add files, Rebuild, and Replacement sheets now use typed guided workflows with one
  current decision, independent progress/severity cues, neutral pristine states, and sticky
  progression actions.
- Review and result screens now prioritize task decisions, write destinations, warnings,
  remediation, and physical next steps; technical details remain available but secondary.
- Drawer focus, keyboard traversal, async preparation/running feedback, narrow Kit layout,
  long-path rendering, security copy, and semantic action contrast have dedicated regressions.
- The duplicate legacy guided-workspace presentation path was removed. Guided tasks build only
  the auxiliary advanced groups they actually render.
- The approved visual suite contains 66 SVG baselines and exercises all workflows at 160x48,
  120x32, and 80x24, plus Settings, light theme, all six final reviews, wide/narrow results, and
  file-picker/prototype states.

## Executive Decision

Do not try to finish this with another TCSS spacing pass.

Keep Create backup as the reference for a simple, single-page setup form. Redesign Restore,
Add files, Rebuild, and Replace recovery sheets as guided step stacks because their controls are
dependent and their workflows are naturally sequential. Keep Recovery kit and Settings as compact
forms. Give all of them the same shell, status language, focus treatment, responsive rules, review
surface, and result surface.

The core interaction for a dependent workflow is:

```text
Restore files                                      Step 2 of 4

[complete] 1  Backup source     4 scanned pages, latest update 3
[current ] 2  Unlock backup
              ( ) Passphrase
              ( ) Recovery sheets
              ( ) Recovery payload files
              [Enter passphrase]
[locked  ] 3  Version to restore
[locked  ] 4  Destination

                                              [Continue]
```

Exactly one step is expanded. Completed steps collapse to a useful one-line summary. Future steps
remain visible so the user understands the workflow, but controls do not appear until they are
relevant. A completed step can be reopened without losing state.

## Current-State Audit

The audit covered the current working tree, not the last commit. Screens were exercised at
160x48, 120x32, and 80x24, including the file picker and final review.

### What Is Working

- The application has real task-specific workspaces and a shared task/domain layer.
- Create backup has a recognizable hierarchy: files, recovery method, destination, and advanced.
- The write action is gated behind a final review.
- File picking, task execution, result handling, contextual help, and keyboard navigation are real.
- Advanced options are generally separated from the beginner path.
- Task state persists while moving between workflows.

These are valuable foundations. The redesign should preserve them rather than restart the app.

### What Makes The App Feel Unfinished

1. The UI exposes validation state instead of user intent.

   Initial screens repeatedly say `Required`, `Missing`, or `Fix` before the user has interacted.
   A pristine field is treated like an error. Restore, for example, shows a source error, an empty
   source box, and a `Fix: Load backup` action for the same missing decision.

2. Dependent decisions are presented as one long form.

   Restore shows unlock, version, destination, and advanced authentication before a backup has
   been understood. Add files and Replace recovery sheets show controls that cannot be meaningful
   until a source is loaded. The user must decode ordering from validation messages and scrolling.

3. Defaults and completion contradict each other.

   Some sections say `Complete` while every radio marker is empty. A default is either selected and
   visible, or it still needs confirmation and the section is incomplete. It cannot be both.

4. The visual hierarchy is nearly flat.

   Section titles, validation copy, helper copy, values, disabled actions, and buttons mostly use
   neighboring shades of gray. Large dark surfaces do not create useful grouping. Focus is visible,
   but the current decision is not visually dominant.

5. Wide layouts are stretched and sparse; narrow layouts collide.

   At 160x48, Rebuild leaves a large empty middle area while required output content falls near the
   bottom. At 80x24, Add files field labels, values, and buttons collide; Replace recovery sheets
   overflows its three source actions; title and readiness text clip each other.

6. Unavailable controls remain visible as dim prose.

   `Use this backup`, fingerprint actions, and source-dependent output controls are shown before
   they can be used, followed by text explaining why they cannot be used. Hide conditional
   controls until their condition is true.

7. The primary action uses system language.

   `Fix backup`, `Fix backup source`, and `Fix files` sound like error recovery, not task progress.
   The action bar also duplicates the active section's action instead of advancing the workflow.

8. Final review is an internal report, not a decision screen.

   The Markdown table of contents, checklist, warnings, plan summary, read paths, output paths,
   safety notes, trust notes, recovery notes, and preview all compete in one long document. The
   first viewport does not reliably answer the three review questions: what am I doing, where will
   it write, and what deserves caution?

9. Responsive behavior is local and inconsistent.

   Several widgets inspect width independently and fixed-width field rows remain horizontal after
   the available workspace can no longer support them. The navigation toggle occupies a full-height
   strip with its symbol vertically centered instead of behaving like a top-aligned drawer button.

10. Existing tests prove geometry, not design quality.

    Tests catch some overlap and focus regressions, but there are no approved visual snapshots for
    the workflow states. A layout can satisfy the region assertions and still look broken.

## Product And Visual Direction

The desired character is a quiet archival instrument: trustworthy, deliberate, and technical
without adopting a hacker aesthetic.

### Visual Language

- Use graphite backgrounds, warm off-white primary text, and one restrained teal accent for focus
  and primary actions.
- Reserve amber for a consequential warning and red for an actual blocking error after user
  interaction. Do not color every incomplete field as a warning.
- Use green sparingly for final success, not for every completed row.
- Use one surface level for the workspace and one raised level for the active step or modal. Avoid
  a stack of bordered boxes.
- Use a consistent spacing scale of 0, 1, 2, and 3 terminal cells.
- Use concise sentence-case labels. Section context should allow buttons such as `Browse...`,
  `Paste text...`, `Change`, and `Remove` instead of repeating the workflow noun in every action.
- Every state must have a non-color cue: status word, marker, or both.
- Keep full fingerprints and long paths in technical details. Main views use a stable middle
  truncation plus an unambiguous filename or short fingerprint suffix.

### Information Hierarchy

Each normal workflow screen has four levels, in this order:

1. Task title and compact progress.
2. Step overview showing current, complete, and upcoming work.
3. The current step's direct controls.
4. One sticky progression action.

Helper prose is not a fifth permanent level. Keep only contextual safety or consequence text near
the control that needs it. Move explanatory material to `?` help and detailed consequences to final
review.

## Interaction Contract

### Step States

Presentation state must distinguish:

- `locked`: a prerequisite is missing; summary is visible, controls are not.
- `available`: the step can be opened and has not been touched.
- `current`: the one expanded step.
- `complete`: domain requirements are satisfied; show a compact summary.
- `warning`: complete, but a user decision deserves attention.
- `error`: invalid after interaction or after a review attempt.

Domain `TaskValidation` remains the source of truth for execution. App-level UI state owns the
active step, touched fields, attempted review, and expanded advanced panel. Do not put UI lifecycle
state into crypto or format models.

### Progression

- `Continue` advances only when the current step is complete.
- The last step changes the action to the task-specific review label.
- A local control performs the local edit. The sticky action does not duplicate `Browse...` or
  `Enter passphrase...`.
- `Ctrl+R` opens review when ready. Otherwise it opens and focuses the first invalid or incomplete
  step and shows one field-level message.
- Reopening an earlier step keeps later values unless that edit makes them invalid. Invalidated
  dependent values are cleared by existing domain mutation rules and the next affected step opens.
- Source parsing or assessment happens after source selection, before advancement. Show a local
  loading indicator and a typed result; do not wait until final review to reveal a parse failure.

### Focus And Keyboard

- Tab and Shift+Tab are the canonical control traversal keys.
- Enter activates buttons and opens a selected step. Space changes radio, switch, and list state.
- `j`/`k` may mirror up/down when a focused widget supports it, but must not override text input.
- `h` returns to workflow navigation; `l` returns to the current step.
- Opening a modal focuses its first meaningful control. Closing it returns focus to the invoking
  control, not merely the workspace.
- Moving focus to a control also scrolls its full label, value, and validation message into view.
- The footer shows only high-value global bindings. Put the complete shortcut list in help.

### Validation And Copy

- A pristine required field uses a neutral empty state, not `! Required`.
- After a failed Continue or Review, show one specific error next to the field.
- A warning states the consequence and the user's available response. Avoid generic `Check` copy.
- The same sentence must not appear in the step, action bar, toast, and review.
- Use `recovery sheets` consistently in user-facing UI. Keep `document`, `payload`, and internal
  terminology only where users genuinely select that artifact type.

## Responsive Layout Contract

Use Textual's app/screen horizontal and vertical breakpoints so one responsive state owns the whole
screen. Do not let each widget invent a different threshold.

### Wide: 132 Columns And Above

- Navigation rail: 30 to 34 columns.
- Workspace: left-aligned with a maximum readable content width; do not stretch field values across
  all remaining columns.
- Step headers may keep title, summary, and status on one row.
- File picker uses browser plus selected-items panes.
- Final review may use a summary column and a details column, but no Markdown table of contents.

### Standard: 88 To 131 Columns

- Navigation is a top-aligned overlay drawer opened by a compact button.
- Step headers use title on the first row and summary/status on the second when needed.
- Field label, value, and action can remain horizontal only when all three fit without truncation.
- Button rows wrap into multiple rows through explicit layout variants, not clipping.

### Narrow: Below 88 Columns Or Below 28 Rows

- Navigation stays closed by default and the drawer button remains at the top.
- Hide the marketing subtitle and version before allowing task title or progress to clip.
- Field rows become a vertical label/value/action stack.
- Source-method actions become a vertical list.
- Only the current step body is expanded; completed step summaries stay one line where possible.
- File picker uses a single pane. Selected items replace or stack below the browser only after the
  first selection.
- Modals use the full available screen with a fixed header and action row.
- The sticky action bar reserves its own row and the scroll container has enough bottom space that
  the final control can be fully visible above it.

Support 80x24 as a polished target. At 60x20, the application may require scrolling, but text and
controls must not overlap or extend beyond the screen.

## Screen Specifications

### Create Backup

Keep its current single-page model and use it as the visual reference. Make only consistency fixes:

- Show the recommended recovery method as selected when it is the effective default.
- Reduce the missing-files state to one empty selector plus its Browse action.
- Put an existing-output warning next to the destination value rather than in both status and value.
- Show selected item count and concise paths.
- Keep Advanced collapsed and summarize only non-default decisions.
- Apply the new theme, focus, responsive field rows, review, and result surfaces.

### Restore Files

Use four steps:

1. Backup source

   Offer scanned pages, pasted recovery text, and payload files as explicit source methods. After
   selection, show source type, material count, short backup identity, detected version range when
   known, and a Change action. Put expected-head fingerprint under Advanced source checks.

2. Unlock

   Use a native `RadioSet`. Render exactly one contextual control below it: enter passphrase, choose
   recovery sheets, or choose recovery payload files. Never show the radio set plus a redundant
   `Set unlock method` button. Secret values are represented only as `Passphrase set`.

3. Version

   Visibly select `Newest loaded version` by default. Show Initial and Specific only as alternative
   choices. When Specific is selected, reveal update number or fingerprint controls inline. If
   source assessment can enumerate versions, show them in a compact list.

4. Destination

   Show one restore-folder field. A non-empty destination warning appears only after selection and
   names the conflict consequence. Authentication policy lives in a collapsed Advanced section.

The empty first viewport should contain the task title, all four step names, and the three source
methods. It should not show unlock errors or output errors yet.

### Add Files To Backup

Use four steps:

1. Existing backup

   Choose either a backup folder or scanned pages. Do not render both as simultaneous path fields.
   For scanned pages, reveal the freshness decision only after assessment: expected fingerprint or
   explicit acceptance of the supplied latest version. For a backup folder, hide scan-only trust
   controls.

2. Files to add or replace

   Use a selection list with Add files, Add folder, Remove selected, and Clear all. Show file and
   folder counts. Keep replacement semantics in a short warning only when a selected path matches
   known backup content; keep deletion/rename guidance in help.

3. Unlock

   Reuse the shared Unlock control and its secret-handling rules.

4. Update and output

   If the source is a backup folder, show that the update will be appended there and do not show a
   disabled output picker. If the source is scanned pages, show an enabled output-folder picker.
   Keep recovery policy, signing-key recovery, QR density, and base folder under Advanced, with a
   concise summary of non-default decisions.

The final review must make `add or replace`, the destination, the source freshness decision, and
the new recovery material explicit.

### Rebuild Backup

Use three steps:

1. Existing backup

   Choose backup folder or scanned pages. Show one selected-source summary. Do not reserve a large
   empty path-list box before a source exists.

2. Unlock and trust

   Reuse Unlock. Show the fingerprint/stale-source decision only for scanned pages. Do not render a
   generic `Rebuild options` section for folder sources.

3. Output

   Put output folder, paper size, and print design together. QR density and trust-source overrides
   remain Advanced. Move `existing backup files are not deleted or modified` to final review; it
   should not occupy the main form.

At 160x48, the source chooser and all three step headers must stay in the upper half of the
workspace. Required output must never appear detached at the bottom of an otherwise empty screen.

### Create Replacement Recovery Sheets

Use four steps and visually separate existing material from new material:

1. Existing backup

   Reuse the Restore source chooser and scanned-source trust behavior.

2. Unlock existing backup

   Reuse Unlock, but label current recovery sheets clearly so they are not confused with the new
   sheets being created.

3. New recovery set

   Show Recommended as the visible default. Custom reveals a purpose-built quorum control with
   threshold and count inputs plus a live sentence such as `Create 5 sheets; any 3 can restore`.
   Passphrase-sheet policy is a direct Select or Switch with its dependent count shown inline.

4. Output and signature recovery

   Show destination first. Signing-key recovery is an Advanced subsection and reveals only the
   controls for Off, Same quorum, Custom quorum, or Replace existing. Existing signing-key payload
   selection appears only for Replace existing.

The result screen must include a strong next-step sequence: print, test a sheet, then retire the old
set. This is more useful than repeating implementation metadata.

### Recovery Kit

Keep a compact single-page form:

- Group kit type, paper size, and print design into one `Document setup` section.
- Put the output PDF directly below it.
- Keep QR sizing in Advanced because automatic sizing is the normal path.
- Show an existing-file warning inline with the selected path.
- Avoid a large sparse surface at wide sizes; constrain the form width.
- Review should lead with the exact PDF path and overwrite state.

### Settings

Keep tabs and autosave, then align it with the shared presentation system:

- Make the save state unambiguous: Saving, Saved, or Save failed.
- Do not show `Changed` beside a value after it has been successfully persisted.
- Constrain control width at wide sizes rather than stretching Select widgets.
- Use the same focus, warning, field-row, responsive, and modal rules as workflows.
- Keep reset actions scoped to the active tab and keep config-file actions on the Config tab.

## Shared Surfaces

### Navigation And Header

- Reduce the wide rail width and top-align its collapsed drawer control.
- Keep numbered task shortcuts, but reduce decorative group chrome.
- Show a small state marker only for tasks whose session state has changed: in progress, ready, or
  needs attention. Do not put detailed validation in the rail.
- Keep `ETHERNITY` as the strong brand signal. On narrow screens, hide subtitle and version before
  hiding workflow information.
- Replace the decorative progress bar with step progress for guided workflows and a compact
  `2 of 3 ready` label for simple forms.

### File Picker

- Wide mode keeps browser and selection panes, but the selected pane has an explicit empty state and
  item count.
- Narrow mode is single-pane until at least one item is selected; selected items can then replace
  the browser or appear in a short stack.
- Use `Select`, `Use current folder`, `Remove`, and `Cancel` labels that match the mode. `Choose` is
  too ambiguous.
- Keep current location visible and make Up a compact icon/text action rather than a wide block.
- Disable the final Select action until the selection is valid and explain one validation problem
  beside the action.

### Final Review

Replace the Markdown report and table of contents with purpose-built widgets.

First viewport:

```text
Review restore

Source       4 scanned pages, latest update 3
Restore      Newest loaded version
Destination ~/Recovered

[warning only when needed]
Destination contains 2 items. Matching names may be replaced.

Technical details (collapsed)

                                      [Back] [Restore files]
```

Rules:

- Show the task outcome, source, output, and consequential warning once.
- Put full read paths, fingerprints, trust notes, recovery notes, and failure behavior in a
  collapsed Technical details section.
- Do not repeat a generic checklist when every item is already complete.
- Use task-specific labels for the final action.
- For warnings that require explicit consent, use a checkbox or a separate confirmation step rather
  than relying on passive prose.

### Result And Failure

- Success begins with what was created or restored, where it is, and the next physical action.
- Keep Open folder, Copy paths, and Copy fingerprint only when applicable.
- Show output paths in a compact selectable list, not a paragraph.
- Failure leads with the user-actionable error and a `Return to <step>` action.
- Keep stack traces and raw logs collapsed under Technical details.
- A partial-write warning must name the affected folder and remain visually distinct from the
  ordinary error message.

## Presentation Architecture

The current `WorkspaceGroup.kind: str` model is too weak for a polished interface and is not truly
driving composition. Replace it incrementally with typed step and control presentations.

Recommended shape:

```text
WorkflowPresentation
  task_key
  title
  active_step
  steps: tuple[StepPresentation, ...]
  primary_action
  review_summary

StepPresentation
  key
  title
  state
  summary
  body: Source | Unlock | PathSelection | Destination | Quorum | Options
  issue
```

Use discriminated dataclasses or Pydantic models for step bodies. Do not use string `kind` values
plus string lookups such as `value(group, "output")` for new work.

Shared app widgets should include:

- `WorkflowStepStack`
- `WorkflowStepHeader`
- `SourceChooser`
- `PathSelectionEditor`
- `UnlockEditor`
- `DestinationEditor`
- `QuorumEditor`
- `InlineNotice`
- `ReviewSummary`
- `ResultSummary`

Task-specific workspace modules compose those widgets and keep task language local. They must not
parse preview strings or reach into crypto/format layers.

Replace `WorkspaceChoiceList`, which is a custom `OptionList`, with native `RadioSet`/`RadioButton`
for mutually exclusive choices. Continue using `SelectionList`, `Select`, `MaskedInput`, `Switch`,
`DirectoryTree`, `Collapsible`, and `LoadingIndicator` for the jobs they actually model.

Likely implementation areas:

- `src/ethernity/tasks/presentation/models.py`
- `src/ethernity/tasks/presentation/workflow_*.py`
- `src/ethernity/app/workspaces/*.py`
- `src/ethernity/app/widgets/*.py`
- `src/ethernity/app/theme.tcss`
- `src/ethernity/app/shell.py`
- `src/ethernity/app/widgets/task_canvas.py`
- `src/ethernity/app/widgets/action_bar.py`
- `src/ethernity/app/screens/file_picker.py`
- `src/ethernity/app/screens/review_task.py`
- `src/ethernity/app/screens/task_result.py`
- `src/ethernity/app/workflow_registry.py`

Do not change format, recovery, crypto, QR, or rendering semantics to accomplish the redesign.
When source inspection needs more data, expose a typed read-only assessment from the existing task
or planning layer. Never derive backup identity or recovery state by parsing display text.

## Implementation Slices

Each slice ends with approved screenshots. Do not merge all layout work and defer visual review to
the end.

### Slice 0: Design Contract And Harness

- Add deterministic fake presentation states for empty, partial, ready, warning, error, running,
  success, and failure.
- Add SVG snapshot tooling using the official Textual snapshot approach.
- Capture the existing UI as audit evidence, not as the new golden baseline.
- Build a non-functional Restore prototype at 160x48, 120x32, and 80x24.
- Approve spacing, hierarchy, colors, step behavior, and narrow layout before wiring task mutations.

Exit gate: Restore prototype looks intentional at all three target sizes and no control is clipped.

### Slice 1: Shell And Shared Primitives

- Register horizontal and vertical responsive breakpoints at app/screen level.
- Implement the Ethernity palette and semantic focus/warning/error/success styles.
- Fix header, navigation drawer, task header, footer, and sticky action behavior.
- Build step stack, source chooser, path selection, unlock, destination, quorum, and notice widgets.
- Make the file picker responsive and mode-specific.
- Add keyboard and focus-return tests for every shared primitive.

Exit gate: component gallery snapshots pass at wide, standard, narrow, dark, light, and no-color
configurations.

### Slice 2: Restore End To End

- Replace the Restore workspace with the four-step flow.
- Add typed source assessment presentation and local loading/error states.
- Replace final review with the structured review surface.
- Verify success and failure result paths.
- Exercise scanned pages, pasted text, payload files, all unlock methods, all target modes,
  authentication policy, fingerprint checks, destination conflict, and retry.

Exit gate: a new user can complete Restore without help, and each first missing requirement opens
the correct step and control.

### Slice 3: Add Files And Rebuild

- Reuse source, unlock, destination, and trust widgets.
- Implement source-dependent visibility and output behavior for Add files.
- Implement the three-step Rebuild flow and eliminate its large empty viewport.
- Preserve existing preparation/assessment and execution behavior.
- Add review summaries specific to append/update and rebuild consequences.

Exit gate: folder and scanned-source paths each show only applicable controls, with no disabled
ghost actions or explanatory filler.

### Slice 4: Replacement Recovery Sheets

- Implement existing-source, unlock, new-recovery-set, and output/signature steps.
- Build and verify the quorum editor.
- Add conditional passphrase and signing-key recovery controls.
- Add retirement guidance to the success result.
- Stress-test the densest state with long paths and all advanced controls.

Exit gate: the 80x24 dense state has no horizontal overflow, clipped controls, or ambiguous old/new
recovery terminology.

### Slice 5: Harmonize Simple Forms

- Apply shared theme and responsive primitives to Create backup without changing its successful
  mental model.
- Compact Recovery kit.
- Align Settings save feedback and field sizing.
- Complete help and copy terminology sweep.

Exit gate: the product reads as one application, not one good screen plus several separate tools.

### Slice 6: Regression And Product Review

- Complete the snapshot matrix and interaction matrix.
- Run keyboard-only, mouse, no-color, long-path, empty-state, warning, error, running, success, and
  failure passes.
- Review every target screenshot manually. A passing snapshot means unchanged, not good.
- Run repository lint, format, type, unit, integration, and terminal app gates.

Exit gate: all acceptance criteria below are evidenced by tests and approved screenshots.

## Acceptance Criteria

### Every Workflow

- The first viewport has one obvious current decision and one clear progression action.
- Pristine fields are neutral; errors appear only after interaction or review attempt.
- Effective defaults are visibly selected.
- Future or inapplicable controls are hidden, not dimmed with explanatory prose.
- No requirement, warning, output path, or consequence is repeated in visible regions.
- Long paths and the longest localized-ready English labels do not overlap neighboring controls.
- The last focusable control can scroll fully above the sticky action bar.
- Keyboard and mouse can complete the same workflow.
- Secrets are never rendered back to the screen.

### Target Sizes

- 160x48: content is constrained and balanced; no large accidental voids.
- 120x32: navigation drawer, step summaries, field rows, and action bar remain coherent.
- 80x24: no clipping, overlap, horizontal overflow, or three-button rows.
- 60x20: scrolling may be required, but every control remains reachable and legible.

### Review And Result

- Review's first viewport shows action, source, destination, and any consequential warning.
- Technical details are available without dominating the beginner path.
- Final action wording exactly matches the operation.
- Success identifies outputs and next physical steps.
- Failure identifies the step to revisit and keeps raw diagnostics secondary.

## Verification Matrix

Use a small but meaningful visual matrix rather than snapshotting every permutation.

- Each workflow: empty and ready at 120x32.
- Restore: partial, warning, error, review, success, and failure at 120x32.
- Replace recovery sheets: empty and densest advanced state at 160x48, 120x32, and 80x24.
- Shell/navigation: wide, standard drawer closed/open, and narrow.
- File picker: files, folder, save file, empty selection, populated selection, and invalid save name.
- Shared controls: default, focused, disabled, loading, warning, error, and no-color.
- Review/result: wide and narrow, long paths, overwrite warning, partial failure.

Automated checks:

- Textual Pilot interaction tests for progression, focus, modal return, and source-dependent reveal.
- SVG snapshot tests with reviewed baselines.
- Geometry assertions that every visible widget is inside its container and outside the action bar.
- Copy-ownership tests for duplicate visible messages.
- Task presentation tests for default selection, step state, warning ownership, and exact focus target.
- Existing task model, terminal app integration, Ruff, formatting, Pyrefly, and relevant unit and
  integration tests.

## Non-Goals

- No changes to backup format or compatibility.
- No cryptographic or recovery-policy redesign.
- No new TUI framework.
- No decorative animation program. Keyboard movement should remain immediate.
- No attempt to expose every scriptable CLI flag in the beginner path.
- No direct edits to generated recovery kit bundles or visual baselines unrelated to the TUI.

## References

- Textual app breakpoints and test API: https://textual.textualize.io/api/app/
- Textual testing and SVG snapshots: https://textual.textualize.io/guide/testing/
- Textual widget gallery: https://textual.textualize.io/widget_gallery/
- Textual `RadioSet`: https://textual.textualize.io/widgets/radioset/
- Textual `SelectionList`: https://textual.textualize.io/widgets/selection_list/
- Textual `ContentSwitcher`: https://textual.textualize.io/widgets/content_switcher/
