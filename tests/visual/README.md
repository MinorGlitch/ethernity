# TUI visual regression tests

The visual tests follow Textual's [testing guidance](https://textual.textualize.io/guide/testing/)
and use its built-in `App.run_test()` and `App.export_screenshot()` APIs to render exact SVG
screenshots at fixed terminal sizes. The normal test run compares those renders against reviewed
files in `snapshots/`. The harness forces truecolor independently of the invoking terminal and
normalizes Rich's generated SVG IDs so local and CI renders remain comparable.

The official `pytest-textual-snapshot` plugin was evaluated first. Its current `1.1.0` release pins
Syrupy 4.8, which requires pytest below 9, while this repository pins pytest 9.1.1. Keeping the
small comparator here avoids downgrading the repository's test runner or adding an unsatisfiable
dependency. It can be replaced with the official plugin once its released dependency range
supports pytest 9.

## Review workflow

1. Run `uv run pytest tests/visual -v`.
2. On a mismatch, open the reported `*.received.svg` next to its reviewed baseline and compare the
   complete terminal at the target size. A changed snapshot is not automatically an improvement.
3. Check hierarchy, focus, wrapping, clipping, horizontal overflow, sticky actions, and non-color
   status cues. Inspect every target size rather than approving from a diff alone.
4. Only after that review, run
   `uv run pytest tests/visual -v --update-tui-snapshots` to replace the baselines.
5. Run `uv run pytest tests/visual -v` again without the update flag.

The fixtures do not invoke format parsing, cryptography, filesystem discovery, or workflow
execution. The production suite renders the real `EthernityApp` shell and real workflow widgets at
`160x48`, `120x32`, and `80x24`. It covers empty and configured states for every workflow, including
a dense expanded Replacement configuration, plus the Settings workspace at all three sizes.

The matrix adds a small set of high-value cross-cutting captures rather than multiplying every
state by every presentation variant:

- Restore and Settings are captured in the light theme at `120x32`; the full workflow matrix stays
  on the default dark theme.
- Final review is captured at `120x32` for Backup, Restore, Add Files, Rebuild, Replacement, and Kit.
  Geometry checks require each task's decision facts to be visible without scrolling.
- Results include Restore success and failure at `120x32`, Backup success at `160x48`, and a narrow
  partial Rebuild failure at `80x24`. Together they cover remediation, reviewed destinations,
  partial outputs, copy/open destination actions, and a document fingerprint action.

Geometry assertions keep sticky actions inside their owning region, reject horizontal scrolling,
and require the key review/result facts and destination actions to remain in the first viewport.
Deterministic absolute fixture paths are used only for presentation, and every capture checks a
sentinel passphrase to ensure secrets never reach a screenshot.

The file-picker gate uses a tiny checked-in filesystem fixture to cover its compact empty state and
standard selected state without depending on host directory contents. Operating-system shell
dialogs remain outside this SVG suite because desktop state is not a deterministic screenshot
input.
