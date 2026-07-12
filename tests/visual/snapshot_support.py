"""Small deterministic SVG snapshot harness built on Textual's screenshot API."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import os
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from unittest.mock import patch

from textual.app import App
from textual.pilot import Pilot

RunBeforeCapture = Callable[[App[object], Pilot[object]], Awaitable[None] | None]


def capture_svg(
    app_factory: Callable[[], App[object]],
    *,
    terminal_size: tuple[int, int],
    title: str,
    run_before: RunBeforeCapture | None = None,
) -> str:
    """Run an app headlessly at a fixed size and return a settled SVG render."""

    with patch.dict(
        os.environ,
        {"COLORTERM": "truecolor", "TERM": "xterm-256color"},
        clear=False,
    ):
        os.environ.pop("NO_COLOR", None)
        app = app_factory()

    async def capture() -> str:
        app.animation_level = "none"
        async with app.run_test(
            size=terminal_size,
            tooltips=False,
            notifications=False,
        ) as pilot:
            await pilot.pause()
            app.screen.refresh(layout=True)
            await pilot.pause()
            if run_before is not None:
                result = run_before(app, pilot)
                if inspect.isawaitable(result):
                    await result
                await pilot.pause()
                app.screen.refresh(layout=True)
                await pilot.pause()
            return app.export_screenshot(title=title, simplify=True)

    return _normalize_svg(asyncio.run(capture()))


def assert_svg_snapshot(
    actual_svg: str,
    baseline_path: Path,
    *,
    update: bool,
) -> None:
    """Compare an SVG exactly, leaving a viewable received file when it differs."""

    actual_svg = _normalize_svg(actual_svg)
    received_path = baseline_path.with_name(f"{baseline_path.stem}.received.svg")

    if update:
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(actual_svg, encoding="utf-8")
        received_path.unlink(missing_ok=True)
        return

    if not baseline_path.exists():
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        received_path.write_text(actual_svg, encoding="utf-8")
        raise AssertionError(
            f"Missing TUI SVG baseline: {baseline_path}\n"
            f"Review the received render at {received_path}, then run this test with "
            "--update-tui-snapshots."
        )

    expected_svg = _normalize_svg(baseline_path.read_text(encoding="utf-8"))
    if actual_svg == expected_svg:
        received_path.unlink(missing_ok=True)
        return

    received_path.write_text(actual_svg, encoding="utf-8")
    expected_digest = hashlib.sha256(expected_svg.encode()).hexdigest()[:12]
    actual_digest = hashlib.sha256(actual_svg.encode()).hexdigest()[:12]
    mismatch = _first_mismatch(expected_svg, actual_svg)
    raise AssertionError(
        f"TUI SVG changed at {mismatch}.\n"
        f"Expected {expected_digest}; received {actual_digest}.\n"
        f"Compare {received_path} with {baseline_path}. If the render is intentional and has "
        "been reviewed, rerun with --update-tui-snapshots."
    )


def _normalize_svg(svg: str) -> str:
    svg = re.sub(r"\bterminal-\d+-([\w-]+)", r"terminal-\1", svg)
    return svg.replace("\r\n", "\n").rstrip() + "\n"


def _first_mismatch(expected: str, actual: str) -> str:
    for index, (expected_character, actual_character) in enumerate(zip(expected, actual)):
        if expected_character != actual_character:
            line = expected.count("\n", 0, index) + 1
            line_start = expected.rfind("\n", 0, index) + 1
            return f"line {line}, column {index - line_start + 1}"
    return f"byte {min(len(expected), len(actual)) + 1}"
