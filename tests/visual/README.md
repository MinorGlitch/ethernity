# TUI visual regression tests

The visual tests follow Textual's [testing guidance](https://textual.textualize.io/guide/testing/)
and use its built-in `App.run_test()` and `App.export_screenshot()` APIs to render exact SVG
screenshots at fixed terminal sizes. The normal test run compares those renders against reviewed
files in `snapshots/`. The harness forces truecolor independently of the invoking terminal and
normalizes Rich's generated SVG IDs so local and CI renders remain comparable. UI interactions
use the shared `run_app_test` session in `tests/support/app.py`, which waits for queued messages,
layout, focus changes, and animations before capture.

The evaluated `pytest-textual-snapshot` version `1.1.0` pins
Syrupy 4.8, which requires pytest below 9, while this repository pins pytest 9.1.1. Keeping the
small comparator here avoids downgrading the repository's test runner or adding an unsatisfiable
dependency.

## Review workflow

1. Run `uv run pytest tests/visual -n 2 -v`.
2. On a mismatch, open the reported `*.received.svg` next to its reviewed baseline and compare the
   complete terminal at the target size. A changed snapshot is not automatically an improvement.
3. Check hierarchy, focus, wrapping, clipping, horizontal overflow, sticky actions, and non-color
   status cues. Inspect every target size rather than approving from a diff alone.
4. Only after that review, run
   `uv run pytest tests/visual -v --update-tui-snapshots` to replace the baselines.
5. Run `uv run pytest tests/visual -n 2 -v` again without the update flag.

The fixtures seed typed `BackupEstimate` and `SourceAssessment` results through task cache APIs.
They do not invoke format parsing, cryptography, filesystem discovery, or workflow execution.
The production suite renders the real `EthernityApp` shell and workflow widgets at `220x48`, `160x48`,
`120x32`, and `80x24`. It covers empty and configured tasks, expanded file lists, Unlock and Version
sections, a dense Replacement configuration, and Settings at all three sizes.
Backup Files, Recovery, and Print setup are captured separately. The workbench rail becomes a
horizontal step strip below 110 columns, and the live summary is hidden at that size. Final review
and results fill the workspace, with their actions kept at the bottom.

Additional snapshots cover themes, reviews, and results:

- Open dropdowns are captured in every workflow, Settings and the Manage/Tools menus. They check
  padded choices, alignment with the selected value, bounded width and popup placement in dark
  and light themes, including short terminals. Unit tests check that padding is highlighted and
  clickable, as well as wrapped labels, scrolling, keyboard navigation and option-list updates.
- Restore and Settings are captured in the light theme at `120x32`, plus Backup and Restore at
  `80x24`. The full workflow matrix uses the default dark theme.
- Final review is captured at `120x32` and `80x24` for Backup, Restore, Add Files, Rebuild,
  Replacement, and Kit.
  Geometry checks require each task's review details to be visible without scrolling.
- Results include Restore success and failure at `120x32`, Backup success at `160x48` and `80x24`,
  and a partial Rebuild failure at `80x24`. They cover remediation, reviewed destinations, partial
  outputs, copy/open actions, fingerprints, PDF page counts, and automatic generated-document
  recovery tests.

Geometry assertions keep sticky actions inside their owning region, reject horizontal scrolling,
and require the main review/result details and destination actions to remain in the first viewport.
Path inputs may scroll their text horizontally while their controls stay within the form width.
Deterministic absolute fixture paths are used only for presentation, and every capture checks a
sentinel passphrase to ensure secrets never reach a screenshot.

The file-picker gate uses a tiny checked-in filesystem fixture to cover its compact empty state and
standard selected state without depending on host directory contents. Operating-system shell
dialogs remain outside this SVG suite because desktop state is not a deterministic screenshot
input.
