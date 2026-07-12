# Terminal CLI Gap Audit

Date: 2026-07-07

Scope: the new Textual terminal app under `src/ethernity/app`, task state under
`src/ethernity/tasks`, and scriptable task entrypoints under `src/ethernity/run`.

This file is a working audit ledger. It tracks UI affordances that were fake, backend
capabilities that are real but missing from the new UI, and places where the current evidence is
not strong enough to call the redesign complete.

## Fixed in the current pass

### Custom kit source removed from public task surfaces

Evidence:

- `PrintKitTaskState` no longer has `bundle_path`.
- `PrintKitTaskState.execute()` calls `render_kit_qr_document(...)` without any custom bundle
  input.
- The kit workspace no longer renders a `Kit source` group or `workspace-kit-bundle` action.
- `ethernity run print-kit` no longer exposes `--bundle`.
- `render_kit_qr_document(...)` no longer accepts `bundle_path`.
- `_load_kit_bundle(...)` loads only the built-in packaged bundle or the local development
  `kit/dist` fallback.
- Custom bundle path tests were removed; the remaining tests cover packaged and development bundle
  loading only.

Reason: the user-facing product only supports Ethernity-supplied recovery kits.

### Unlock radio choices now do real work

Evidence:

- Selecting `Recovery documents` opens the file picker and writes to `recovery_documents`.
- Selecting `Recovery payload files` opens the file picker and writes to `recovery_payload_files`.
- Selecting `Passphrase` opens the passphrase modal.
- The `Set unlock` workspace button follows the selected unlock method instead of always opening
  passphrase.
- Unlock methods clear competing unlock values when a real value is chosen.

Affected workflows:

- Restore files
- Add files
- Rebuild backup
- Replace recovery docs

### Freshness acceptance is no longer automatic

Evidence:

- Picking scan sources now resets `allow_stale_head` to false.
- The `Accept source` button is what sets `allow_stale_head` to true.
- Add files now has a real freshness confirmation path instead of a dead button.

Affected workflows:

- Add files
- Rebuild backup
- Replace recovery docs

### Backup/add-files file and folder selections are separated

Evidence:

- File/folder pickers split selected directories into `input_dirs`.
- Selected files remain in `input_paths`.
- Reopening the picker preserves both files and directories.

Reason: backend args distinguish `input` from `input_dir`.

### Source type selection is explicit for restore and replacement flows

Evidence:

- Restore source actions now expose compact `Scans`, `Text`, and `Payloads` controls.
- Replace recovery source actions now expose compact `Scans`, `Text`, and `Payloads` controls.
- Recovery text choices write to `recovery_text_file`.
- Payload choices write to `payloads_file`.
- Scan choices write to `source_paths`.
- The choices clear competing source fields so execution args do not silently combine stale
  selections.

Affected workflows:

- Restore files
- Replace recovery docs

### Expected head fingerprint is exposed

Evidence:

- Add files, rebuild, and replace recovery docs now expose a `Fingerprint` action when scan sources
  are present.
- The fingerprint modal writes to `expected_head_doc_hash`.
- Setting a fingerprint clears `allow_stale_head`.
- Accepting stale source clears `expected_head_doc_hash`.
- Changing scan sources clears any old expected fingerprint.

Affected workflows:

- Add files
- Rebuild backup
- Replace recovery docs

### Restore target fingerprint is exposed

Evidence:

- Restore target controls include an update-number path and a fingerprint path.
- The fingerprint editor writes `extension_doc_hash`.
- Setting a fingerprint switches the restore target to `specific_update`.
- Setting a fingerprint clears `extension_index` so numeric and hash targets cannot conflict.
- Choosing latest, original, or a numeric update clears stale fingerprint state.

Affected workflow:

- Restore files

### Restore expected latest-head fingerprint is exposed

Evidence:

- `RestoreTaskState` already modeled `expected_head_doc_hash` and passes it through to
  `RecoverArgs.expected_head_doc_hash`.
- `ethernity run restore` already exposes `--expected-head`.
- The restore workspace now exposes a compact `Hash` control in the backup source section.
- The fingerprint editor writes the real `RestoreTaskState.expected_head_doc_hash` field.
- Changing the restore source clears the previous expected-head fingerprint so stale values do not
  silently follow a new source.
- Restore preview/final review now includes the expected latest-head status.
- `test_textual_app_restore_expected_head_fingerprint_is_real_control` verifies the UI control,
  args mapping, preview text, and source-change clearing behavior.

Affected workflow:

- Restore files

### Final review is structured instead of a prose dump

Evidence:

- Final review now separates status, blocking issues, checklist, destination, and previewed
  documents.
- The redundant `FINAL_REVIEW_REQUIRED` warning is filtered out of the review modal.
- The modal title is the workflow name rather than a repeated "Final review: ..." prefix.
- Review actions remain fixed below the scrollable body, and the primary action remains disabled
  until validation is ready.

### Sticky action duplication and workspace overlap removed

Evidence:

- The bottom action bar now contains only the primary review action.
- Duplicate sticky setup buttons for input, passphrase, and output were removed; those controls now
  live only in the relevant workspace sections.
- Shared one-line workspace rows no longer reserve two rows of height.
- Workspace radio controls no longer reserve two rows per option.
- `test_textual_app_workspace_buttons_do_not_overlap_primary_action` verifies visible workspace
  buttons stay above the sticky primary action across all workflows at a 120x48 terminal size.
- `test_textual_app_restore_target_fingerprint_is_real_control` now clicks the real workspace
  fingerprint button and opens the correct editor.

### Replace recovery docs signing-key recovery is editable

Evidence:

- The replace recovery workspace exposes a real `Signing key` select with Off, Same quorum, and
  Custom quorum choices.
- Same quorum enables `mint_signing_key_recovery` without custom threshold/count overrides.
- Custom quorum opens the editor and writes `signing_key_recovery_threshold` and
  `signing_key_recovery_count`.
- Off clears signing-key recovery state and disables signing-key shard minting.
- The preview and `to_mint_args()` include signing-key recovery documents when enabled.

### Backup advanced creation controls are exposed

Evidence:

- The backup workspace now exposes passphrase, generated passphrase word count, input base folder,
  signing-key storage mode, and signing-key shard quorum controls.
- Generated passphrase words and custom passphrase clear each other before assignment, matching the
  task model invariant.
- Setting signing-key shard quorum switches signing-key storage to sharded mode and writes
  `signing_key_shard_threshold` and `signing_key_shard_count`.
- `BackupTaskState.preview()` now lists signing-key recovery documents when they will be written.
- `BackupTaskState.validate_task()` blocks incompatible signing-key sharding combinations instead
  of silently ignoring them.
- Generated passphrase word count is a select control backed by the allowed BIP39 word counts
  rather than a free-text modal.
- `BackupTaskState` rejects unsupported generated passphrase word counts on construction or
  assignment instead of allowing execution to fail later.
- `ethernity run backup` exposes `--passphrase-words` with the same allowed BIP39 word counts used
  by the backend.
- `test_run_backup_yes_executes_task_model` verifies the scriptable backup command writes
  `BackupTaskState.passphrase_words` and passes it through to `BackupArgs.passphrase_words`.
- `test_textual_app_backup_advanced_controls_are_real` verifies the Textual select writes allowed
  values and clears custom passphrases.
- `test_backup_task_rejects_unsupported_generated_passphrase_word_count` verifies invalid counts
  such as 8 are rejected at the task model boundary.

### Scriptable rebuild print layout is exposed

Evidence:

- `RebuildTaskState` models `paper_size` and `design`.
- `RebuildTaskState.to_compact_args()` passes those values to `CompactArgs.paper` and
  `CompactArgs.design`.
- The Textual rebuild workspace already exposed Paper and Design controls.
- `ethernity run rebuild` now exposes `--paper` and `--design`.
- `test_run_rebuild_yes_executes_task_model` verifies the scriptable rebuild command writes
  `RebuildTaskState.paper_size` and `RebuildTaskState.design`, and passes both through to
  `CompactArgs`.

### Add-files advanced update options are exposed

Evidence:

- The add-files workspace now exposes base folder, unlock policy, recovery document policy/quorum,
  and signing-key storage/quorum controls.
- Unlock policy uses a select for the real allowed values: self-contained and reuse-root.
- Recovery document policy uses a select for default, no new documents, or custom quorum.
- Signing-key storage uses a select for default policy, not stored, or sharded.
- Custom recovery and signing-key quorums write the real `AddFilesTaskState` threshold/count
  fields and flow through to `ExtendArgs`.
- Choosing reuse-root clears incompatible recovery document overrides.
- `AddFilesTaskState.validate_task()` now blocks invalid advanced combinations before execution.

### Restore unsigned legacy recovery policy is exposed

Evidence:

- The restore workspace now has an Authentication policy select.
- The select writes the real `RestoreTaskState.allow_unsigned` field.
- `RestoreTaskState.preview()` includes the current authentication policy.
- `RestoreTaskState.to_recover_args()` passes `allow_unsigned` through to `RecoverArgs`.

### Authentication fallback/payload material is exposed

Evidence:

- Restore and rebuild task states model `auth_text_file` and `auth_payloads_file`.
- Restore and rebuild reject conflicting auth text and auth payload file choices.
- Restore and rebuild previews show the selected authentication material.
- Restore and rebuild workspaces expose an Authentication material select with automatic, text, and
  payload-file choices.
- `ethernity run restore` and `ethernity run rebuild` expose `--auth-text`,
  `--auth-fallback-file`, and `--auth-payloads-file`.
- `RestoreTaskState.to_recover_args()` passes auth fallback/payload files through to
  `RecoverArgs`.
- `RebuildTaskState.to_compact_args()` passes auth fallback/payload files through to
  `CompactArgs`.

Note: raw in-memory `auth_frames` remains an internal API value, not a user-facing terminal input.

### Fake add-files authentication material flags were removed

Evidence:

- `ExtendArgs` has no `auth_fallback_file` or `auth_payloads_file` fields.
- `AddFilesTaskState` does not model authentication fallback/payload material.
- `ethernity run add-files` no longer exposes `--auth-text`, `--auth-fallback-file`, or
  `--auth-payloads-file`.
- `test_run_add_files_rejects_unsupported_auth_material_options` verifies the removed flag is
  rejected instead of being silently ignored.

Reason: add-files authentication material controls were a fake feature in this surface. Restore and
rebuild still expose the real authentication material support.

### Task states reject made-up user-facing fields

Evidence:

- Every user-facing task state now uses Pydantic `extra="forbid"` in its model config:
  backup, restore, add-files, rebuild, replace-recovery-docs, print-kit, and settings.
- This closes the failure mode where a CLI, workspace, or future shim could pass an unsupported
  keyword and have Pydantic silently ignore it.
- `test_user_facing_task_states_reject_unknown_fields` verifies all task states reject
  `made_up_feature=True` with a validation error.

Reason: this is the structural guard that would have caught the removed fake add-files auth flags.
Unknown fields must fail loudly so advertised controls cannot drift away from real task model
capability.

### Per-run QR chunk size is exposed where the backend supports it

Evidence:

- `BackupTaskState`, `AddFilesTaskState`, and `RebuildTaskState` model `qr_chunk_size`.
- `PrintKitTaskState` models `chunk_size`.
- Those task states reject non-positive chunk sizes.
- `BackupTaskState.to_backup_args()` passes the value to `BackupArgs.qr_chunk_size`.
- `AddFilesTaskState.to_extend_args()` passes the value to `ExtendArgs.qr_chunk_size`.
- `RebuildTaskState.to_compact_args()` passes the value to `CompactArgs.qr_chunk_size`.
- `PrintKitTaskState.execute()` passes the value to `render_kit_qr_document(..., chunk_size=...)`.
- The backup, add-files, rebuild, and kit workspaces expose real QR sizing fields.
- `ethernity run backup`, `ethernity run add-files`, `ethernity run rebuild`, and
  `ethernity run print-kit` expose `--qr-chunk-size` with positive integer validation.
- `test_textual_app_edit_kit_qr_chunk_size` verifies the kit workspace writes
  `PrintKitTaskState.chunk_size` and reflects it in the preview.
- `test_run_print_kit_yes_executes_task_model` verifies `ethernity run print-kit --qr-chunk-size`
  writes `PrintKitTaskState.chunk_size`.

Deliberate non-feature:

- `replace-recovery-docs` does not expose per-run QR chunk size because `MintArgs` has no
  `qr_chunk_size` field. Adding a control there would be fake.

### Shard quorum counts honor the cryptographic limit

Evidence:

- Task-level quorum validation uses the sharding layer's `MAX_SHARES` limit of 255.
- Backup, add-files, and replace-recovery-docs task states reject shard thresholds/counts above
  255 instead of letting impossible values reach execution.
- The Textual threshold/count parser rejects values above 255 before assigning task state.
- Custom quorum editor copy names the 1 to 255 range.
- `ethernity run backup`, `ethernity run add-files`, and
  `ethernity run replace-recovery-docs` cap shard threshold/count Click options at 255.
- `test_textual_app_quorum_parser_rejects_counts_above_shamir_limit` verifies Textual parsing.
- `test_task_models_reject_quorum_counts_above_shamir_limit` verifies task-state boundaries.
- `test_run_shard_count_options_reject_values_above_shamir_limit` verifies scriptable command
  validation.

### Replace signing-key recovery payloads are exposed

Evidence:

- `ReplaceRecoveryDocsTaskState` already models `signing_key_recovery_payload_files`.
- `ReplaceRecoveryDocsTaskState.to_mint_args()` passes those files to
  `MintArgs.signing_key_shard_payloads_file`.
- `ethernity run replace-recovery-docs` already exposes `--signing-key-payloads-file`.
- The replace-recovery-docs workspace now exposes a `Key payloads` picker in the signing-key
  recovery area.
- The preview shows selected signing-key recovery payload files.
- `test_textual_app_replace_recovery_signing_key_payloads_are_real_picker` verifies the picker
  writes the task state and execution args.
- `test_replace_recovery_docs_signing_key_count_enables_signing_key_replacements` verifies the task
  model preview and args include signing-key recovery payload files.

### Settings descriptors are aligned with the config API surface

Evidence:

- `test_settings_descriptors_cover_config_api_snapshot_surface` compares every settings descriptor
  path against every leaf value in `get_api_config_snapshot(DEFAULT_CONFIG_PATH).values`.
- `test_settings_enum_descriptors_reference_config_api_options` verifies enum descriptors point at
  real option lists from the config API snapshot.
- The settings view is therefore aligned to the API-backed user-facing config surface, not the
  lower-level raw TOML parser internals.

Deliberate non-feature:

- Low-level QR image fields such as `qr.scale`, `qr.border`, `qr.kind`, `qr.dark`, and `qr.light`
  are parsed by the config loader, but they are not exposed by the config API snapshot. They should
  not appear in the beginner settings view unless they are intentionally promoted into the
  user-facing settings API.

### Old interactive CLI modules and compatibility entrypoints are removed

Evidence:

- `test_new_terminal_layer_does_not_import_old_interactive_cli` verifies the new app, task, and
  runner layers do not import old Typer/bootstrap/prompt UI modules.
- `test_source_tree_no_longer_imports_questionary_or_prompt_toolkit` verifies source imports do not
  reintroduce Typer, Questionary, or prompt-toolkit.
- `test_old_prompt_and_typer_source_files_are_removed` verifies old command, wizard, workspace,
  orchestrator, and prompt helper files are absent.
- `test_cli_package_no_longer_exports_legacy_entrypoints_or_command_runners` verifies the legacy
  `ethernity.cli` package no longer exports the root `main` handoff, old interactive app, old
  command runners, old shared constants, old shared types, or old crypto helpers.
- `test_cli_module_entrypoint_is_removed` and
  `test_old_prompt_and_typer_source_files_are_removed` verify the `python -m ethernity.cli`
  compatibility entrypoint is gone.
- The old `ethernity.cli.bootstrap` root dispatch package was removed. `src/ethernity/main.py`
  owns the root no-args terminal launch, root help/version output, and `ethernity run` dispatch.
- The `ethernity.app`, `ethernity.app.screens`, `ethernity.app.widgets`, `ethernity.run`,
  `ethernity.run.commands`, `ethernity.tasks`, and `ethernity.cli` package roots are package
  markers only, not compatibility barrels.
- The `ethernity.app.main` forwarding module was removed; tests now import `EthernityApp` from its
  owning module, `ethernity.app.application`.
- A live-code search for old command module imports, old prompt libraries, and top-level task
  command usage found only planning/release documentation and boundary tests.

### Non-settings workspaces are task-specific and sectioned

Evidence:

- `TaskWorkspaces` uses a `ContentSwitcher` with separate workspace widgets for backup, restore,
  add-files, rebuild, replace-recovery-docs, and kit.
- Every non-settings workspace is composed from direct `.workspace-section` children instead of a
  flat checklist dump.
- `test_textual_app_workspace_shows_real_flow_controls` verifies the center workspace exposes real
  flow controls instead of the old checklist placeholder surface.
- `test_textual_app_workspaces_are_grouped_into_sections` verifies each rendered workspace is
  grouped into the expected section count at a 120x48 terminal size.
- `test_textual_app_blocked_workflows_show_inline_summary_and_fix_action` verifies blocked
  workflows use inline status plus one primary fix action instead of duplicate side-panel blockers.
- `test_textual_app_workspace_buttons_do_not_overlap_primary_action` verifies visible workspace
  buttons do not collide with the sticky primary action across all non-settings workflows.
- `test_textual_app_palette_changes_shell_colors` verifies Textual theme changes still affect the
  shell colors.
- `test_textual_app_supports_hjkl_and_arrow_navigation` verifies arrow and `hjkl` navigation
  across task rail and workspace focus.
- `test_textual_app_modals_open_centered` verifies edit, file picker, and final review modals open
  away from the corner.
- `test_textual_app_common_terminal_sizes_keep_workspaces_readable` verifies wide, medium, and
  narrow terminal sizes keep the center workspace at usable width, keep the outcome rail visible,
  and keep visible workspace/action button labels inside their button regions.
- The side rails were narrowed from fixed 28/42 columns to 24/32 columns so a 96-column terminal
  still leaves at least 36 columns for the center workspace.
- Crowded source-action labels were shortened (`Scans`, `Text`, `Payloads`, `Accept`, `Hash`) and
  the replace-recovery-docs source controls were split across two rows instead of cramming five
  buttons into one row.

### Workspace actions no longer advertise controls that are not rendered

Evidence:

- The kit presentation model no longer advertises a fake `workspace-kit-variant` button; the kit
  variant is a real select control (`workspace-kit-variant-select`).
- Backup, add-files, and rebuild presentation groups now include their rendered QR chunk size
  buttons, so the model no longer omits live controls.
- Stale workspace button handlers for removed controls were deleted:
  `workspace-add-files-recovery`, `workspace-add-files-signing-key-shards`, and
  `workspace-kit-variant`.
- `test_textual_app_workspace_buttons_match_presentation_actions` verifies every rendered
  `workspace-*` button in every non-settings workspace is present in the presentation model, and
  every presentation action has a corresponding rendered button.
- `test_textual_app_workspace_controls_have_event_paths` verifies rendered workspace selects and
  radio sets use an explicit event path or the shared paper/design select path.

Remaining risk:

- This is automated layout and copy-ownership evidence, not a human screenshot approval. Final
  visual polish may still need human review for taste, but the main spacing, overlap, truncation,
  and width regressions now have repeatable tests.

## Confirmed missing functionality

No remaining missing capability has been fully confirmed in this audit pass. The items below still
describe residual subjective review risk rather than known missing behavior.

## Residual subjective risk

### Manual screenshot taste review

The automated Textual evidence now covers task-specific grouping, copy ownership, overlap,
palette/theme propagation, navigation, modal placement, wide/medium/narrow workspace width, and
visible button-label truncation. The remaining gap is a subjective screenshot review for taste:
whether the density and alignment feel good enough to ship, beyond what widget regions can prove.

## Final verification

- `uv run --extra dev pytest tests/unit/test_terminal_app.py tests/unit/test_terminal_run_cli.py
  tests/unit/test_terminal_task_models.py tests/unit/test_terminal_hard_break_boundaries.py
  tests/unit/test_main_entrypoints.py -q`
- `uv run --extra dev ruff check src/ethernity/main.py src/ethernity/app src/ethernity/run
  src/ethernity/tasks tests/unit/test_terminal_app.py tests/unit/test_terminal_run_cli.py
  tests/unit/test_terminal_task_models.py tests/unit/test_terminal_hard_break_boundaries.py
  tests/unit/test_main_entrypoints.py`
- `uv run --extra dev ruff format --check src/ethernity/main.py src/ethernity/app
  src/ethernity/run src/ethernity/tasks tests/unit/test_terminal_app.py
  tests/unit/test_terminal_run_cli.py tests/unit/test_terminal_task_models.py
  tests/unit/test_terminal_hard_break_boundaries.py tests/unit/test_main_entrypoints.py`
- `uv run --extra dev pyrefly check src/ethernity/main.py src/ethernity/app src/ethernity/run
  src/ethernity/tasks`
- `uv run ethernity --help`
- `uv run ethernity run --help`
- `uv run ethernity --version`
