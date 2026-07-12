"""Pytest controls for TUI SVG baselines."""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("tui snapshots")
    group.addoption(
        "--update-tui-snapshots",
        action="store_true",
        default=False,
        help="Replace reviewed TUI SVG baselines with the current render.",
    )


@pytest.fixture
def update_tui_snapshots(request: pytest.FixtureRequest) -> bool:
    """Whether this explicitly invoked test run may replace visual baselines."""

    return bool(request.config.getoption("--update-tui-snapshots"))
