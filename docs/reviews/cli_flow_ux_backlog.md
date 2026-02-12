# CLI Flow and UX Backlog

Date: 2026-02-09
Input: findings from `docs/reviews/cli_flow_ux_review.md`

## Prioritization
Priority model:
- `P1`: broken safety/flow, fix first
- `P2`: major friction/confusion
- `P3`: polish consistency

## Implementation Tracks

### Track A: Input Safety and Deterministic Non-Interactive Behavior
Priority: P1

1. A1 - Reject empty implicit stdin backup payloads (`F-001`)
- Target files:
  - `src/ethernity/cli/flows/backup.py`
  - `src/ethernity/cli/io/inputs.py`
- Change shape:
  - detect zero-byte stdin when `-` is inferred or provided
  - emit clear error and exit code 2
- Regression tests:
  - add non-TTY empty-stdin backup failure test in `tests/unit/test_cli_backup.py`
  - optional e2e subprocess case in `tests/e2e/test_end_to_end_cli.py`
- Acceptance:
  - `printf '' | ethernity backup` must fail with actionable message.

2. A2 - Clarify recover input behavior for empty non-interactive stdin (`F-002`)
- Target files:
  - `src/ethernity/cli/commands/recover.py`
  - `src/ethernity/cli/flows/recover_plan.py`
- Change shape:
  - avoid implicit fallback parse when stdin has no bytes
  - show explicit usage guidance for missing input mode
- Regression tests:
  - add `recover` empty-stdin test in `tests/unit/test_cli_recover_validation.py`
- Acceptance:
  - `printf '' | ethernity recover` fails with input-selection guidance, not fallback parser internals.

### Track B: Warning and Status Output Correctness
Priority: P2

1. B1 - Move `--skip-auth-check` warning to post-validation phase (`F-003`)
- Target files:
  - `src/ethernity/cli/flows/recover_plan.py`
  - optionally `src/ethernity/cli/flows/recover_wizard.py`
- Change shape:
  - emit warning only after input frames are successfully resolved
- Regression tests:
  - new unit test: missing-input + `--skip-auth-check` should not print warning first
- Acceptance:
  - warning appears only for runs that proceed beyond input validation.

2. B2 - Disable `Live` spinner behavior for non-TTY output (`F-004`)
- Target files:
  - `src/ethernity/cli/ui/__init__.py`
- Change shape:
  - gate `status()` spinner with terminal detection
  - use plain, line-oriented status text in non-TTY contexts
- Regression tests:
  - add output-shape test in `tests/unit/test_cli_ui.py` and/or subprocess test in `tests/unit/test_cli_typer.py`
- Acceptance:
  - no concatenated spinner artifacts in captured logs.

### Track C: Discoverability and Error Message Quality
Priority: P2/P3

1. C1 - Improve root non-TTY no-subcommand message (`F-005`)
- Target files:
  - `src/ethernity/cli/app.py`
- Change shape:
  - mention `ethernity --help` rather than listing only two commands
- Regression tests:
  - assert stable message content and exit code in CLI invocation test
- Acceptance:
  - message provides complete discovery path.

2. C2 - Friendly missing-bundle error for `kit --bundle` (`F-006`)
- Target files:
  - `src/ethernity/cli/flows/kit.py`
- Change shape:
  - wrap `Path.read_bytes()` failures in domain-specific `ValueError`
- Regression tests:
  - missing bundle path case in `tests/unit/test_cli_typer.py` or new kit flow test
- Acceptance:
  - output is actionable and consistent with other command errors.

## Execution Order
1. Track A (`A1`, `A2`) - safety first.
2. Track B (`B1`, `B2`) - correctness and log quality.
3. Track C (`C1`, `C2`) - discoverability and consistency.

## Suggested PR Slicing
1. PR-1: `A1 + tests`
2. PR-2: `A2 + tests`
3. PR-3: `B1 + B2 + tests`
4. PR-4: `C1 + C2 + tests`

## Regression Test Checklist by Track
- `A1`: non-TTY empty stdin backup, explicit stdin with non-empty content, standard input-file backup unchanged.
- `A2`: non-TTY recover with empty stdin, explicit `--fallback-file -` behavior, explicit payload/scan paths unchanged.
- `B1`: warning ordering and final summary wording with `--skip-auth-check`.
- `B2`: non-TTY status output snapshots (no spinner artifacts), TTY behavior retained.
- `C1`: no-subcommand message includes `--help` guidance.
- `C2`: missing bundle path returns friendly error text and code 2.

## Risks and Mitigations
1. Risk: changing implicit stdin behavior can break existing scripts.
- Mitigation: include explicit compatibility note in release notes and preserve `--input -` and `--fallback-file -` as canonical automation paths.

2. Risk: TTY detection differences across platforms.
- Mitigation: use existing `isatty` helper path and add tests that mock stream behavior.

3. Risk: warning timing change may alter expected logs.
- Mitigation: update tests to assert warning appears in successful recovery plans only.
