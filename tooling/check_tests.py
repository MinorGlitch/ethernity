"""Run the same Python test selections and coverage gates locally and in CI."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from tooling.release_resources import REQUIRED_KIT_ENTRIES

ROOT = Path(__file__).resolve().parents[1]
UI_SPLIT = (
    "tests/ui",
    "--splits=2",
    "--splitting-algorithm=least_duration",
    "--durations-path=tests/ui/durations.json",
)
SUITES = {
    "core": ("tests/unit", "tests/integration"),
    "rendering": ("tests/rendering",),
    "ui-1": (*UI_SPLIT, "--group=1"),
    "ui-2": (*UI_SPLIT, "--group=2"),
    "visual": ("tests/visual",),
    "e2e": ("tests/e2e",),
    "portability": (
        "tests/unit",
        "tests/ui",
        "tests/rendering",
        "tests/integration",
        "-m",
        "portability",
    ),
}
COVERAGE_SUITES = ("core", "rendering", "ui-1", "ui-2")
COVERAGE_GATES = {"src/ethernity/*": 85, "tooling/document_inspector_app/*": 45}


def run_module(module: str, *args: str, env: dict[str, str] | None = None) -> int:
    command = [sys.executable, "-m", module, *args]
    print(f"\n$ {shlex.join(command)}", flush=True)
    return subprocess.run(command, cwd=ROOT, env=env, check=False).returncode


def run_suite(suite: str, results: Path, *, coverage: bool = False) -> int:
    workers = 4 if suite in COVERAGE_SUITES else 2
    args = [
        *SUITES[suite],
        "-n",
        "logical",
        f"--maxprocesses={workers}",
        "--dist=load" if suite == "visual" else "--dist=loadfile",
        "--durations=30",
        f"--junitxml={results / (suite + '.xml')}",
    ]
    env = os.environ.copy()
    env.pop("COVERAGE_FILE", None)
    if suite == "e2e":
        env.setdefault("ETHERNITY_TEST_CLI_TIMEOUT_SECONDS", "300")
    if coverage:
        env["COVERAGE_FILE"] = str(results / f".coverage.{suite}")
        args.extend(("--cov=ethernity", "--cov=tooling.document_inspector_app", "--cov-report="))
    return run_module("pytest", *args, env=env)


def check_coverage(results: Path) -> int:
    files = [results / f".coverage.{suite}" for suite in COVERAGE_SUITES]
    missing = [path.name for path in files if not path.is_file()]
    if missing:
        print(f"Coverage incomplete: missing {', '.join(missing)}.", file=sys.stderr)
        return 1
    data_file = f"--data-file={results / '.coverage'}"
    if run_module("coverage", "combine", data_file, "--keep", *(str(path) for path in files)):
        return 1
    statuses = [
        run_module("coverage", "report", data_file, f"--include={path}", f"--fail-under={minimum}")
        for path, minimum in COVERAGE_GATES.items()
    ]
    return int(any(statuses))


def check_setup() -> bool:
    """Do not call a run complete if optional local tools would silently skip checks."""
    missing = [tool for tool in ("node", "pdftoppm", "pdfinfo") if shutil.which(tool) is None]
    paths = [ROOT / "kit/node_modules"]
    paths.extend(ROOT / "src/ethernity" / entry for entry in sorted(REQUIRED_KIT_ENTRIES))
    missing.extend(str(path.relative_to(ROOT)) for path in paths if not path.exists())
    if missing:
        print(
            f"Missing test prerequisites: {', '.join(missing)}. See CONTRIBUTING.md.",
            file=sys.stderr,
        )
    return not missing


def run_all(results: Path) -> int:
    if not check_setup():
        return 1
    outcomes = {suite: run_suite(suite, results, coverage=True) for suite in COVERAGE_SUITES}
    if any(outcomes.values()):
        print("Coverage gates not checked because a contributing test suite failed.")
        outcomes["coverage"] = 1
    else:
        outcomes["coverage"] = check_coverage(results)
    for suite in ("e2e", "visual"):
        outcomes[suite] = run_suite(suite, results)
    print("\nFull local Python check:")
    for suite, status in outcomes.items():
        print(f"  {suite}: {'FAILED' if status else 'passed'}")
    print("CI still checks other platforms, JavaScript/browser tests, packaging and audits.")
    return int(any(outcomes.values()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", nargs="?", default="all", choices=("all", *SUITES, "coverage"))
    parser.add_argument("--coverage", action="store_true", help="Collect coverage for one CI group")
    parser.add_argument("--results-dir", type=Path, default=ROOT / "test-results")
    args = parser.parse_args(argv)
    if args.coverage and args.suite not in COVERAGE_SUITES:
        parser.error("--coverage is only for core, rendering, ui-1 and ui-2; all includes it")
    results = args.results_dir.resolve()
    results.mkdir(parents=True, exist_ok=True)
    if args.suite == "all":
        return run_all(results)
    if args.suite == "coverage":
        return check_coverage(results)
    print(f"Partial check: {args.suite} only. Run without a suite name for the full Python check.")
    return run_suite(args.suite, results, coverage=args.coverage)


if __name__ == "__main__":
    raise SystemExit(main())
