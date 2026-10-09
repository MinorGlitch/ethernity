# Contributing to Ethernity

## Set up the project

Use Python 3.11 or newer and the uv version required by [pyproject.toml](pyproject.toml).
The browser kit uses npm and Node.js 24.19+ on the 24.x line, or Node.js 26.5 or newer.
Earlier Node versions accept extra gzip members that browsers reject. CI uses Node.js 24.
`npm ci` installs the pinned Zopfli build dependency; no separate compressor is required.

```sh
git clone https://github.com/MinorGlitch/ethernity.git
cd ethernity
uv sync --frozen --extra dev --extra build
```

Build the recovery kit before creating backup documents or running the full test suite:

```sh
cd kit
npm ci
node build_kit.mjs
cd ..
```

Start the terminal app with `uv run ethernity`. Use `uv run ethernity run --help` for scriptable
commands.

## Make a change

Branch from `master` in your fork. Keep a pull request focused on one change and explain the
resulting behavior, how you tested it, and any compatibility impact.

Use Ruff as the only Python formatter, with the configured 100-character line length. Keep imports
at module scope. Reserve `# fmt: off` for cases where restructuring cannot solve the readability
problem.

Write functions in the order the work happens. Give intermediate results useful names when nested
calls make a step hard to follow. Prefer early returns when they reduce nesting. Use names that
describe the operation without repeating context already supplied by the module.

Extract a helper for a distinct operation, shared behavior, or a necessary boundary. Keep related
logic together; avoid forwarding wrappers and new context objects whose only purpose is to satisfy
a size limit. Comments and docstrings should explain constraints and reasons that the code does not
already express. In tests, use shared fixtures for repeated setup and patching.

The [repository guidance](AGENTS.md) describes module boundaries and rules for coding agents.
Task and recovery behavior belongs in the shared task and workflow layers so the app and commands
use the same rules.

## Check your change

Run the relevant tests while working. Before opening a pull request, run the Python checks:

```sh
uv run ruff check src tests tooling
uv run ruff format --check src tests tooling
uv run pylint src/ethernity tooling
uv run pyrefly check
uv run typos .
uv run pytest tests/unit tests/ui tests/rendering tests/integration -q
```

The full Python suite needs the generated kit bundles and installed npm dependencies from setup.
The [CI workflow](.github/workflows/ci.yml) defines the platform matrix, coverage thresholds, E2E
tests, packaging checks, and dependency audits. Local checks do not replace those gates.
The full unit, UI, rendering and integration suites run on macOS and Windows with Python 3.11,
and on Linux with Python 3.13. The Linux run collects application and document-inspector coverage together,
then checks them separately against the 85% and 45% thresholds. Reporting does not rerun tests.
Python lint, formatting, type checking, and spelling share one CI job with separate result steps.
Each platform, E2E, and terminal snapshot run reports its 30 slowest tests and uploads JUnit
timings for seven days. Failed terminal snapshots also upload their received SVGs.
Job summaries group test time by subsystem and list the slowest cases. These totals include setup
and teardown and are summed across workers, so they can exceed elapsed time. To read a downloaded
JUnit report locally, run `uv run python scripts/summarize_test_timings.py <report-directory>`.

Choose the smallest suite that exercises the change:

| Directory | What it tests |
| --- | --- |
| `tests/unit` | Core rules, parsers, crypto and individual services |
| `tests/ui/components` | Controls and dialogs using production styles |
| `tests/ui/workflows` | Navigation, editing, review and execution wiring in the full app |
| `tests/rendering` | PDF generation, layout, printed content and scan validation |
| `tests/integration` | Backup/recovery workflows and Python/browser integration |
| `tests/e2e` | Command-line round trips and frozen released-backup compatibility |
| `tests/visual` | Terminal screenshots and responsive layout checks |

Keep a control's behavior matrix in a small component app. Use `WidgetApp` from
`tests/support/widgets.py` when it needs Ethernity's themes, styles and breakpoints. Full workflow
tests should cover the control's connection to task state. Shared render cases must retain their
content, geometry, decoding and appearance checks; tests that damage a PDF need private copies.

Tests should fail when the behavior they protect breaks. Check output content, state changes,
or failure handling; avoid tests that only construct a dataclass, repeat source code, or check
that an old module was deleted. Keep rendering cases in the shared template matrix where possible.
Released-backup fixtures must remain unchanged.

For a quick check of native paths, file publication, worker limits, and UI event handling, run:

```sh
uv run pytest tests/unit tests/ui tests/rendering tests/integration -m portability -q
```

CI runs this selection separately on Linux with Python 3.11 to check the minimum supported Python
version there. Windows and macOS run these tests as part of their full Python 3.11 suites.
Mark a test `portability` when it covers a platform boundary or an asynchronous UI regression and
is fast enough for this check.

UI tests use `run_app_test` from `tests/support/app.py`. It drains event chains, waits for layout
and animations, and finishes each key before sending the next. This avoids relying on CPU-idle
timing, which differs between platforms. Tests for rapid input should send actions without an
intervening pause, as the navigation regression does.
`press()` already settles each key, so an immediate extra `pause()` is unnecessary. The helper
waits for in-flight handlers and deferred layout callbacks, and interrupts its wait when the app
fails. Resizing waits for the screen's resize handler and the child updates it produces, since
the requested size changes before layout catches up. Timer-driven resize and button feedback
waits resume on UI activity and recheck timer state without repeatedly draining every widget.
Do not replace these guarantees with fixed sleeps.

For background workers and future timers, use the bounded waits in `tests/support/pilot.py`.
Wait for the state change the test needs, such as a completed worker. Use the `set_home` fixture
for home-directory overrides; unittest-based tests use `tests.support.environment.home_environment`.
Navigation awaits workspace mounting. Widgets are created on first use and retained when switching
tasks, so tests must open a workspace before querying its controls.

Layout suites can opt into `reuse_qr_images` to reuse identical payload/configuration images.
`rendered_sample` supplies a private copy of a shared sample PDF for output-validation tests.
Keep these fixtures out of codec tests and tests that change rendering internals. The existing
decoding, appearance, and content assertions still run.

Golden and visual suites can run in two worker processes:

```sh
uv run pytest tests/e2e -n 2 --dist loadfile -q
uv run pytest tests/visual -n 2 -q
```

Keep `--dist loadfile` for E2E tests so each frozen-profile class retains its shared setup and
scan cache. Both commands run every test with the same assertions and baselines as a serial run.
The worker count is bounded because recovery uses substantial memory. Use `-n 0` for a serial run.

Repository hooks are available with `uv run pre-commit run --all-files`. They include Python and
kit checks plus a small format test selection.

### Python readability

Ruff checks common mistakes, outdated syntax, unnecessary `else` branches, unused suppression
comments, and function complexity. Pylint checks duplication and deeply nested blocks. Both are
required checks in CI and pre-commit; their settings live in [pyproject.toml](pyproject.toml).
Pyrefly remains the type checker, and Ruff remains the only formatter.

Review each finding before changing code. Complexity thresholds identify functions worth reading;
splitting a function into trivial helpers just to pass a limit makes it harder to follow. Fix one
coherent area at a time, verify its behavior, and keep the resulting changes reviewable.

### Browser kit

Edit the source under `kit/`. From that directory, run:

```sh
npm run lint
npm run format:check
npm test
```

When checking the generated browser app or packaging, rebuild with `node build_kit.mjs`. Install
the test browsers with `npx playwright install --with-deps chromium webkit`, then run
`npm run test:browser`. The shared smoke tests open local HTML files in both engines and restore
frozen older backups and a compressed update chain. To check another engine, install it with
`npx playwright install firefox` and run `npm run test:browser -- firefox`.

The build creates the default and scanner bundles under `src/ethernity/resources/kit/`.
Do not edit or commit these generated HTML files. CI generates them for packages and releases.

Both variants compile the page and recovery worker together. The page starts a worker from the
same inline script, so shared crypto code is stored only once in the HTML. Keep decryption and
update reconstruction in that worker; the page handles input, scanning, and results.

### Rendering and terminal UI

The [PDF template guide](docs/render_templates.md) covers adding a design and the shared
rendering engine.

For PDF layout changes, run:

```sh
uv run python scripts/render_visual_baselines.py --output-dir ./tmp/render-review --rasterize never
uv run pytest tests/rendering/test_render_visual_baselines.py -n 2 -v
```

Inspect the generated PDFs. For terminal layout changes, run `uv run pytest tests/visual -n 2 -v` and
follow the [visual review workflow](tests/visual/README.md#review-workflow). Update visual baselines
only after reviewing the intended change. The `render-visual` CI job checks the PDF review matrix
and terminal snapshots against the reviewed baselines. PDF rendering tests run in the platform suites;
the Linux job installs Poppler so tests that scan composited PDF pages cannot skip for its absence.
Python/browser interoperability tests also run in the platform suites. The `kit-verify` job runs
the JavaScript tests and generated-bundle browser checks.

### Formats, cryptography, and recovery

Test both successful recovery and rejection of invalid inputs. Explain changes to authentication,
resource limits, or access to secrets in the pull request. Run the relevant integration, E2E, and
Python/browser compatibility tests as well as unit tests.

Released v1.0 and v1.1 golden fixtures must remain unchanged and continue to recover. Do not
regenerate them to make a new implementation pass. Use the fixture builders for new format
fixtures and explain intentional changes to unreleased fixtures. The
[release checks](docs/release_files.md#extension-compatibility-checks) list the extension gates.

Report vulnerabilities through [Security](SECURITY.md#report-a-vulnerability).

## Update the documentation

Keep examples aligned with the app and commands. Each document has a different purpose:

| Change | Document |
| --- | --- |
| Installation or first use | [README](README.md) |
| Command procedures | [Advanced operations](docs/advanced_operations.md) |
| Encoded data or decoder rules | [Format specification](docs/format.md) |
| Update output, recovery, replacement sheets, or Rebuild requirements | [Update and recovery rules](docs/extension_publication_rules.md) |
| Reasons for a design choice | [Design decisions](docs/format_rationale.md) |
| Reader or writer compatibility | [Compatibility history](docs/format_history.md) |
| Distributed files or release verification | [Release files](docs/release_files.md) |

For a compatibility change, update the applicable specification and describe old-reader and
new-reader behavior under the unreleased version in the history. Until a version is assigned, use
`Next release`. At release freeze, use the product version with an explicit `unreleased` label;
replace that label with the tag date after release. Update an existing unreleased entry when the
same feature changes during development. Preserve released entries and dates.

Keep development chronology, source-file inventories, and purely editorial changes out of the
compatibility history.
