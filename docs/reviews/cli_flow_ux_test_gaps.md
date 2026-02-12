# CLI Flow and UX Test Gaps

Date: 2026-02-09
Basis: current unit/e2e suite + scenario evidence from `/tmp/cli_help_matrix.txt` and `/tmp/cli_review_matrix.txt`

## Current Coverage Snapshot

### Existing automated coverage (strong)
1. CLI help/version baseline
- `tests/unit/test_cli_typer.py`

2. UI primitives and auth-status formatting
- `tests/unit/test_cli_ui.py`

3. Backup flow internals and kit-index rendering behavior
- `tests/unit/test_cli_backup.py`

4. Recover validation conflicts and fallback parsing
- `tests/unit/test_cli_recover_validation.py`

5. Recover output destination UX defaults
- `tests/unit/test_recover_prompts.py`

6. Recover input parser vectors
- `tests/unit/test_recover_input.py`

7. Core end-to-end happy paths
- `tests/e2e/test_end_to_end_cli.py`

### Coverage map against scenario IDs
- Covered or partially covered: 2, 3, 4, 5, 6, 9, 11, 12, 13, 15, 16, 17, 19, 20, 21, 23, 24, 27, 28, 30, 31, 32, 33, 34, 35, 36
- Missing or manual-heavy: 1, 7, 8, 10, 14, 18, 22, 25, 26, 29

## High-Value Missing Tests

### Gap G-001: Empty stdin backup safety (`S10`, finding `F-001`)
- Current state:
  - no automated assertion for `printf '' | ethernity backup` behavior.
- Add:
  - unit/subprocess test asserting exit code 2 + actionable error text.
- Target file:
  - `tests/unit/test_cli_backup.py`

### Gap G-002: Recover empty non-TTY stdin guidance (`S22`, finding `F-002`)
- Current state:
  - empty stdin recover path is not asserted for UX quality.
- Add:
  - subprocess test asserting missing-input guidance message and code 2.
- Target file:
  - `tests/unit/test_cli_recover_validation.py`

### Gap G-003: Warning ordering for `--skip-auth-check` (`S29`, finding `F-003`)
- Current state:
  - no test for warning ordering relative to input validation errors.
- Add:
  - test ensuring warning is absent before validation failure and present in successful plan execution.
- Target files:
  - `tests/unit/test_cli_recover_validation.py`
  - optionally `tests/unit/test_cli_ui.py` for summary formatting assertion

### Gap G-004: Non-TTY spinner/log shape (`S35/S36`, finding `F-004`)
- Current state:
  - no output-shape test for non-TTY status spinner behavior.
- Add:
  - captured-output test asserting no concatenated spinner artifacts in non-TTY.
- Target file:
  - `tests/unit/test_cli_ui.py`

### Gap G-005: Root no-subcommand discoverability (`S2`, finding `F-005`)
- Current state:
  - no explicit assertion for root no-subcommand error wording.
- Add:
  - CLI invocation test for non-TTY root call message + exit code.
- Target file:
  - `tests/unit/test_cli_typer.py`

### Gap G-006: `kit --bundle` error quality (`S31`, finding `F-006`)
- Current state:
  - error path exercised manually, not validated in tests.
- Add:
  - unit/subprocess case for missing custom bundle file with expected user-facing message.
- Target file:
  - `tests/unit/test_cli_typer.py` or new `tests/unit/test_cli_kit.py`

### Gap G-007: Interactive cancellation gates (`S14`, `S26`)
- Current state:
  - cancel behavior is implemented but not directly asserted for both backup/recover review steps.
- Add:
  - mocked prompt tests where `prompt_yes_no` returns `False`, asserting exit code 1 and cancellation message.
- Target files:
  - `tests/unit/test_cli_backup.py`
  - `tests/unit/test_cli_recover_validation.py` or new recover-wizard test module

### Gap G-008: Shard collection mixed-source duplicate handling (`S25`)
- Current state:
  - behavior exists in code (`_ingest_shard_frame`) but coverage is indirect.
- Add:
  - unit tests for duplicate shard index same payload vs conflicting payload and threshold completion semantics.
- Target file:
  - new `tests/unit/test_recover_shard_prompts.py`

### Gap G-009: Startup failure-path messaging (`S7`)
- Current state:
  - startup install failure path not simulated in tests.
- Add:
  - mock `_playwright_install` failure and assert actionable `Playwright install failed: ...` propagation.
- Target file:
  - `tests/unit/test_cli_startup.py`

## Proposed New Test Cases (Implementation-Ready)

1. `test_backup_empty_stdin_fails_with_missing_input_message`
- Input: empty piped stdin, no `--input`
- Assert: exit code 2, error mentions missing input content.

2. `test_recover_empty_stdin_non_tty_shows_input_guidance`
- Input: empty piped stdin, no explicit input flags
- Assert: exit code 2, message points to `--fallback-file/--payloads-file/--scan`.

3. `test_recover_skip_auth_warning_not_emitted_before_input_validation`
- Input: `recover --skip-auth-check` with no valid input
- Assert: warning is absent or emitted only after successful input parse (depending on final design).

4. `test_status_non_tty_uses_plain_messages_no_spinner_artifacts`
- Input: non-TTY capture of backup flow status
- Assert: stable line-oriented messages.

5. `test_root_no_subcommand_non_tty_references_help`
- Input: non-TTY `ethernity`
- Assert: code 2 and `--help` guidance.

6. `test_kit_custom_bundle_missing_file_returns_actionable_error`
- Input: `kit --bundle /missing`
- Assert: code 2 and stable UX wording.

7. `test_backup_review_cancel_returns_code_1`
- Input: wizard flow with review confirmation `False`
- Assert: code 1 and "Backup cancelled.".

8. `test_recover_review_cancel_returns_code_1`
- Input: recover wizard review confirmation `False`
- Assert: code 1 and "Recovery cancelled.".

9. `test_recover_shard_duplicate_conflict_message`
- Input: two shard frames with same share index but different payload
- Assert: shard conflict error and no acceptance.

10. `test_startup_playwright_install_failure_surfaces_actionable_error`
- Input: mocked install failure
- Assert: CLI exits 2 with clear failure message.

## Validation Commands for Future Remediation PRs
1. `uv run pytest tests/unit/test_cli_typer.py tests/unit/test_cli_ui.py tests/unit/test_cli_backup.py tests/unit/test_cli_recover_validation.py tests/unit/test_recover_prompts.py tests/unit/test_recover_input.py -q`
2. `uv run pytest tests/e2e/test_end_to_end_cli.py -q`
3. add new/updated modules above into the same command set once implemented.
