# CLI Flow and UX Review

Date: 2026-02-09
Repository baseline: current working tree
Review scope: `backup`, `recover`, `kit`, `render`, and root/home command routing

## Summary
This review covered command routing, wizard and non-wizard paths, validation messaging, startup behavior, accessibility/quiet flags, and completion output.

- No runtime code changes were made in this phase.
- Automated checks in this review pass:
  - `uv run pytest tests/unit/test_cli_typer.py tests/unit/test_cli_ui.py tests/unit/test_cli_flows.py tests/unit/test_cli_backup.py tests/unit/test_cli_recover_validation.py tests/unit/test_recover_prompts.py tests/unit/test_recover_input.py -q` -> 61 passed
  - `uv run pytest tests/e2e/test_end_to_end_cli.py -q` -> 3 passed
- Primary UX risks found:
  - empty piped stdin can produce a successful backup with empty payload (P1)
  - recover auto-fallback behavior in non-interactive mode gives ambiguous input errors (P2)
  - skip-auth warning ordering is misleading on invalid input (P2)
  - spinner/live status degrades non-TTY logs (P2)

## Evidence Sources
- Help surface capture: `/tmp/cli_help_matrix.txt`
- Edge/error matrix captures:
  - `/tmp/cli_edge_matrix.txt`
  - `/tmp/cli_edge_matrix2.txt`
  - `/tmp/cli_access_backup.txt`
  - `/tmp/cli_quiet_backup.txt`
- Expanded scenario run capture: `/tmp/cli_review_matrix.txt`

## Scenario Matrix (Plan IDs)
Status legend:
- `PASS` behavior is acceptable for current contract
- `PARTIAL` reviewed but only one side (for example error path) is covered
- `FAIL` behavior does not meet UX expectation
- `MANUAL` interactive scenario, assessed by code path and existing tests but not fully automated in this pass

| ID | Scenario | Status | Evidence |
| --- | --- | --- | --- |
| 1 | `ethernity` with TTY and no subcommand triggers home chooser | MANUAL | Code path in `src/ethernity/cli/app.py:141` and `src/ethernity/cli/ui/__init__.py:316` |
| 2 | `ethernity` without TTY and no subcommand returns actionable error and code 2 | PASS | `/tmp/cli_edge_matrix.txt` (`no_subcommand_nontty`) |
| 3 | `ethernity --help` includes commands and global flags | PASS | `/tmp/cli_help_matrix.txt` |
| 4 | `ethernity --version` exits cleanly | PASS | `/tmp/cli_review_matrix.txt` (`S04`) |
| 5 | Startup path with Playwright already installed | PASS | repeated command invocations + e2e pass |
| 6 | Startup path with `ETHERNITY_SKIP_PLAYWRIGHT_INSTALL=1` | PASS | `/tmp/cli_review_matrix.txt` (`S06`) |
| 7 | Startup path with failed Playwright install emits actionable error | MANUAL | error shape in `src/ethernity/cli/startup.py:185` and `src/ethernity/cli/startup.py:214` |
| 8 | `backup` wizard path (no inputs + TTY) | MANUAL | `src/ethernity/cli/flows/backup.py:400` |
| 9 | `backup` non-wizard with explicit inputs | PASS | e2e `tests/e2e/test_end_to_end_cli.py:37` |
| 10 | `backup` stdin path with no files, non-TTY | FAIL | `/tmp/cli_edge_matrix.txt` (`backup_no_input_nontty`) |
| 11 | `backup` invalid shard flag combinations | PASS | `/tmp/cli_review_matrix.txt` (`S11`) |
| 12 | `backup` invalid passphrase-word count | PASS | `/tmp/cli_review_matrix.txt` (`S12`) |
| 13 | `backup` unknown design handling | PASS | `/tmp/cli_review_matrix.txt` (`S13`) |
| 14 | `backup` review step cancellation | MANUAL | `src/ethernity/cli/flows/backup.py:456` |
| 15 | `backup` completion panel (unsharded) | PASS | `/tmp/cli_edge_matrix.txt` + `/tmp/cli_review_matrix.txt` |
| 16 | `backup` completion panel (sharded) | PASS | `/tmp/cli_review_matrix.txt` (`S16`) |
| 17 | `backup` completion panel (kit index generated) | PASS | `/tmp/cli_review_matrix.txt` (`S17`) |
| 18 | `recover` wizard path with interactive input choice | MANUAL | `src/ethernity/cli/flows/recover_wizard.py:209` |
| 19 | `recover` non-wizard with fallback file | PARTIAL | error path in `/tmp/cli_review_matrix.txt` (`S19`) |
| 20 | `recover` non-wizard with payload file | PARTIAL | e2e success in `tests/e2e/test_end_to_end_cli.py:117`; error path in `S20` |
| 21 | `recover` non-wizard with scan path | PARTIAL | error path in `/tmp/cli_review_matrix.txt` (`S21`) |
| 22 | `recover` stdin fallback path when piped input is present | PARTIAL | empty stdin failure in `S22`; non-empty piped fallback not directly exercised |
| 23 | `recover` conflict validation for fallback vs payloads | PASS | `/tmp/cli_review_matrix.txt` (`S23`) |
| 24 | `recover` conflict validation for auth fallback vs auth payloads | PASS | `/tmp/cli_review_matrix.txt` (`S24`) |
| 25 | `recover` shard collection mixed sources + duplicate share handling | MANUAL | shard ingest behavior in `src/ethernity/cli/flows/prompts.py:191` |
| 26 | `recover` review-step cancellation | MANUAL | `src/ethernity/cli/flows/recover_wizard.py:277` |
| 27 | `recover` output selection single-file | PASS | `tests/unit/test_recover_prompts.py:31` |
| 28 | `recover` output selection multi-file directory | PASS | `tests/unit/test_recover_prompts.py:110` |
| 29 | `recover --skip-auth-check` warning clarity and summary wording | FAIL | `/tmp/cli_review_matrix.txt` (`S29`) |
| 30 | `kit` default generation + completion messaging | PASS | `/tmp/cli_review_matrix.txt` (`S30`) |
| 31 | `kit` custom bundle path and error path | FAIL | `/tmp/cli_review_matrix.txt` (`S31`) |
| 32 | `render` envelope target help clarity | PASS | `/tmp/cli_help_matrix.txt` |
| 33 | `render` PDF output path behavior and errors | PASS | `/tmp/cli_review_matrix.txt` (`S33`) + missing-logo error in `/tmp/cli_edge_matrix2.txt` |
| 34 | `render` DOCX output path behavior and errors | PASS | `/tmp/cli_review_matrix.txt` (`S34`) |
| 35 | Accessibility run with `--no-color --no-animations` | PASS | `/tmp/cli_review_matrix.txt` (`S35`) |
| 36 | Quiet mode across commands | PARTIAL | quiet backup/kit/render validated; recover quiet validated only for error path |

## Findings

### F-001 [P1] Empty piped stdin can create a "successful" empty backup
1. ID and severity: `F-001`, `P1`
2. Reproduction:
   - `printf '' | uv run ethernity backup`
3. Expected behavior:
   - command fails fast with an actionable message that no input content was provided.
4. Actual behavior:
   - command exits 0 and writes `qr_document.pdf` and `recovery_document.pdf`.
5. Impact:
   - operator can believe backup succeeded while backing up no data.
6. Root-cause location:
   - implicit stdin enable: `src/ethernity/cli/flows/backup.py:497`
   - empty stdin accepted as valid input file: `src/ethernity/cli/io/inputs.py:147`
7. Proposed fix shape:
   - add explicit empty-stdin guard when `-` is inferred or passed; reject zero-byte stdin unless an explicit override flag is introduced.
   - optionally stop implicit stdin inference and require explicit `--input -` in non-interactive mode.
8. Required regression test:
   - add a non-TTY backup test asserting `printf '' | ... backup` exits 2 and emits a clear missing-input message.

### F-002 [P2] Non-interactive recover auto-fallback hides missing-input intent
1. ID and severity: `F-002`, `P2`
2. Reproduction:
   - `printf '' | uv run ethernity recover`
3. Expected behavior:
   - explicit missing-input guidance (`--fallback-file`, `--payloads-file`, or `--scan`).
4. Actual behavior:
   - parser-level fallback error (`no recovery lines found`) from implicit fallback mode.
5. Impact:
   - users get a low-level parse error instead of a command-usage correction.
6. Root-cause location:
   - implicit fallback assignment: `src/ethernity/cli/commands/recover.py:158`
7. Proposed fix shape:
   - only auto-assign `fallback_file='-'` when stdin has content, or when explicitly requested.
   - otherwise raise a top-level usage error with actionable options.
8. Required regression test:
   - non-interactive recover with empty stdin should return code 2 with missing-input usage guidance.

### F-003 [P2] `--skip-auth-check` warning appears before input validation
1. ID and severity: `F-003`, `P2`
2. Reproduction:
   - `uv run ethernity recover --skip-auth-check`
3. Expected behavior:
   - warning appears only when recovery proceeds far enough for auth-check behavior to matter.
4. Actual behavior:
   - warning prints before immediate input failure.
5. Impact:
   - warning appears detached from successful execution and can confuse triage.
6. Root-cause location:
   - early warning emission: `src/ethernity/cli/flows/recover_plan.py:87`
7. Proposed fix shape:
   - move warning after successful input/frame collection, or emit it only in summary/output stage.
8. Required regression test:
   - when required inputs are missing, `--skip-auth-check` should not emit the warning before command failure.

### F-004 [P2] Spinner/live status formatting is noisy in non-TTY logs
1. ID and severity: `F-004`, `P2`
2. Reproduction:
   - `uv run ethernity backup` in non-TTY capture context
3. Expected behavior:
   - deterministic line-oriented logs without spinner artifacts.
4. Actual behavior:
   - concatenated spinner updates such as `Starting backup... ✓Preparing payload... ✓...`.
5. Impact:
   - reduced readability in CI logs and scripted wrappers.
6. Root-cause location:
   - `Live(...)` status is used without explicit TTY gating: `src/ethernity/cli/ui/__init__.py:183`
7. Proposed fix shape:
   - mirror `progress()` behavior by disabling live status when output is not a terminal.
   - use one-shot plain messages for non-TTY output.
8. Required regression test:
   - snapshot/assert non-TTY status output contains stable line breaks and no spinner control behavior.

### F-005 [P2] Root command error message under-reports command surface
1. ID and severity: `F-005`, `P2`
2. Reproduction:
   - run `ethernity` without subcommand in non-TTY.
3. Expected behavior:
   - message points users to `--help` and complete command surface.
4. Actual behavior:
   - message mentions only `backup` and `recover`.
5. Impact:
   - reduced discoverability for `kit`, `render`, and `config` commands.
6. Root-cause location:
   - static message: `src/ethernity/cli/app.py:143`
7. Proposed fix shape:
   - replace message with `No subcommand provided. Run 'ethernity --help' for available commands.`
8. Required regression test:
   - non-TTY root invocation should include `--help` guidance and preserve exit code 2.

### F-006 [P3] `kit --bundle` missing-file path leaks raw errno text
1. ID and severity: `F-006`, `P3`
2. Reproduction:
   - `uv run ethernity kit --bundle /no/such/bundle.html`
3. Expected behavior:
   - domain-specific error (`bundle file not found`) with recovery guidance.
4. Actual behavior:
   - raw `Errno 2` from `Path.read_bytes()`.
5. Impact:
   - inconsistent UX versus richer errors in backup/recover/render commands.
6. Root-cause location:
   - direct file read without friendly wrapping: `src/ethernity/cli/flows/kit.py:109`
7. Proposed fix shape:
   - catch `FileNotFoundError`/`OSError` and raise `ValueError` with path + hint (`check --bundle path or omit --bundle`).
8. Required regression test:
   - `kit --bundle` missing file should return code 2 with stable, user-facing error text.

## Open UX Decisions Logged
1. Should non-interactive backup continue supporting implicit stdin (`backup` with no `--input`) when stdin is non-empty?
   - default recommendation: require explicit `--input -` for deterministic automation contracts.
2. Should `recover` continue auto-selecting fallback mode for piped stdin, or require explicit `--fallback-file -`?
   - default recommendation: keep auto mode only when bytes are present, otherwise show input-selection error.

## Positive Notes
- Core help surfaces are clear and well grouped (`Global`, `Accessibility`, `Debug`, command-specific panels).
- Recovery output-path interaction logic has good unit coverage and sensible defaults.
- Backup completion output is rich and includes shard/index variants.
- Accessibility and quiet toggles are generally functioning and testable.
