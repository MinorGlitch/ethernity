# TUI styling

`StyledApp` owns the stylesheet manifest inherited by `EthernityApp` and UI test harnesses.
It applies the stylesheet to lazily created native scrollbars too; Textual skips normal
stylesheet registration for these widgets.

- `theme.tcss` owns native control skins, control height, text roles and shared action rows.
- `workbench.tcss` owns navigation, workflow and settings layouts.
- `dialogs.tcss` owns dialog/document frames and their screen-specific layout.

Keep responsive rules with their owner. Use Textual palette variables for both themes.
Control height is three rows, with one row in short terminals. Navigation and workflow buttons
inherit that same height; their containers size to fit. Inputs, switches, checkboxes, radio choices
and SelectCurrent use real vertical padding; buttons use centered content. Select labels and
arrows stay on one baseline. Compact rules preserve horizontal padding. Centered buttons use
native line padding without an extra CSS inset. Left-aligned step labels have one cell of
horizontal padding. Labels stay on one line.
Field text uses `field-text` to align with controls.
Focus uses side outlines, background and bold text. Primary actions retain their filled color. Never underline an entire widget: terminal renderers
underline its blank padding rows too, producing horizontal rules. Radio focus highlights the
whole candidate row; the radio mark continues to identify the committed value.
Form dropdowns use `FormSelect`, including settings, and fill their control column.
Form dropdowns and navigation menus share the popup frame, `popup-choice` padding and states
in `theme.tcss`. Each choice has one line of padding above and below its label. The whole row
is highlighted and clickable; do not insert dead spacer rows or outer vertical padding.
`FormSelectOverlay` includes that CSS padding in the measured option visual because Textual 8
omits vertical option component padding from its measurements. Prompts, values and native
search/navigation stay unchanged. Long menus scroll without shrinking their choices.
Keep space between form rows and action rows even in short terminals; scroll long forms.
Row spacing must not depend on which sibling is currently visible. Focus must not move a control.
The theme owns scrollbar widths and spacing. Vertical scrollbars reserve three cells: a
one-cell track and a two-cell inset beside the content. Do not add per-screen scrollbar sizes
or outer right padding to simulate that gap. Single-line inputs keep a zero-height horizontal
scrollbar so long values remain visible while their text scrolls.

Reserve the primary color for interaction. Headings use neutral text; warnings use orange,
errors rose, and success green, with labeled notices and borders in addition to color.
The canvas owns the page heading. Completed choices appear beneath their steps in the navigation
rail, using only safe presentation values. Narrow terminals show the step buttons in a horizontal
strip and keep the full choice summaries in their tooltips and review. There is no separate summary
column. The shared shell centers the one-line header, navigation and canvas within 140 columns.
The editor owns its fixed action bar; the heading, scroll viewport and actions fill the editor
width. The outer shell is the only width cap. Do not add smaller caps to forms or dropdowns.
Workflow forms use open `FormSection` groups with neutral headings and thin dividers.
`FormRow` owns the shared label column, controls and notices. Values keep adjacent edit actions
unless their container is too narrow; then actions move below the value.
`ResponsiveActions` measures button labels and uses equal columns that fit the container.
Three source choices share a row at wide sizes; at intermediate sizes the primary action spans
the row above its two alternatives. Hidden actions do not reserve a column.
Rows stack based on their own width.
The workspace owns which sections belong to each step; focus routing uses that same map.
Conditional fields appear only when applicable. Files own base folders; print setup owns QR
density. Recovery separates its method, passphrase and signing-key recovery.
Use named `AppCollapsible` sections for secondary settings. Their closed titles show the selected
values; actionable warnings stay outside the collapsed contents. Edit and Fix actions expand
the target section before focusing its field. Do not reintroduce catch-all Advanced panels.
Simple passphrase and destination edits stay inline. `PassphraseInput` owns the pending edit,
masks it, clears the displayed value on commit, and lets review consume it exactly once.
Task reset discards any pending secret. File browsing remains a dialog with explicit selection.
Backup print setup puts the destination first and opens labelled sample PDFs through the same
renderer as real backups. Samples contain no selected files and live in the app cache.
Put background explanations in Help or control tooltips; keep actionable warnings visible.
Help stays in the top navigation and lists the keyboard shortcuts. Main screens and dialogs
have no shortcut footer, so opening a dialog does not resize the underlying workspace.

Dialogs use `dialog`; review, progress and results use `document`, `document-header`, `document-body`
and the shared detail text classes. Keep IDs for events and queries; add ID styles only for
layout differences. Use native content-sized containers instead of repeating sizing resets.
Review and results use the shared `FormSection` and `FormRow` components inside the same
readable-width document. Headers and footer actions stay fixed while long content scrolls.
The canvas serializes document mounting and removal while preserving navigation and the step
rail. Progress locks navigation until cancellation or completion finishes. Review shows output
before other choices; results put the PDF recovery check before file-management actions.
Done returns to editing and resets a successful Backup. Show each destination once. Use normal Edit buttons and `action_grid` for groups of completion actions.

Change the owning rule and migrate its consumers together. Do not add embedded CSS, duplicate
screen skins, compatibility selectors or a second override stylesheet. Verify shared changes
against the existing production snapshots, including narrow terminals and the light theme.

Settings reuses `WorkbenchSteps` for categories. `SettingField` owns each label, control,
neutral custom marker and `InlineNotice`; `SETTINGS_SECTIONS` groups all task descriptors
without copying their defaults or validation. Settings uses one aligned form rather than
distributing short controls into unrelated columns. Its heading and footer share the form width.
Only actionable issues stay under fields, aligned with their control column.
The fixed footer shows focused-field help and save state. Numeric fields stay short, selects
fill their control column, and paths use the remaining width. Reset applies to the active category.
