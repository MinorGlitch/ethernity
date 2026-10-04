# TUI styling

`EthernityApp.CSS_PATH` is the single stylesheet manifest. Test harnesses use that same list.

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
Focus uses background and bold text. Never underline an entire widget: terminal renderers
underline its blank padding rows too, producing horizontal rules. Radio focus highlights the
whole candidate row; the radio mark continues to identify the committed value.
Form dropdowns use `FormSelect`, including settings. Their width is capped in the theme.
Form dropdowns and navigation menus share the popup frame, `popup-choice` padding and states
in `theme.tcss`. Each choice has one line of padding above and below its label. The whole row
is highlighted and clickable; do not insert dead spacer rows or outer vertical padding.
`FormSelectOverlay` includes that CSS padding in the measured option visual because Textual 8
omits vertical option component padding from its measurements. Prompts, values and native
search/navigation stay unchanged. Long menus scroll without shrinking their choices.
Keep space between form rows and action rows even in short terminals; scroll long forms.

Reserve the primary color for interaction. Headings use neutral text; warnings use orange,
errors rose, and success green, with labeled notices and borders in addition to color.
The canvas owns the page heading. The summary shows completed earlier steps; an empty summary
is hidden. Workflow forms use open `FormSection` groups with neutral headings and thin dividers.
`FormRow` owns the shared label column and keeps values beside their edit actions.
Rows stack based on their own width, including when the summary rail is visible.
The workspace owns which sections belong to each step; focus routing uses that same map.
Conditional fields appear only when applicable. Files own base folders; print setup owns QR
density. Recovery separates its method, passphrase and signing-key recovery.
Do not reintroduce catch-all Advanced panels or per-workflow field layouts.
Put background explanations in Help or control tooltips; keep actionable warnings visible.

Dialogs use `dialog`; Review and Results use `document`, `document-header`, `document-body`
and the shared detail text classes. Keep IDs for events and queries; add ID styles only for
layout differences. Use native content-sized containers instead of repeating sizing resets.

Change the owning rule and migrate its consumers together. Do not add embedded CSS, duplicate
screen skins, compatibility selectors or a second override stylesheet. Verify shared changes
against the existing production snapshots, including narrow terminals and the light theme.

Settings reuses `WorkbenchSteps` for categories. `SettingField` owns each label, control,
neutral custom marker and `InlineNotice`; `SETTINGS_SECTIONS` groups all task descriptors
without copying their defaults or validation. Only actionable issues stay under fields.
The fixed footer shows focused-field help and save state. Numeric fields stay short, selects
have a consistent cap, and paths use the remaining width. Reset applies to the active category.
