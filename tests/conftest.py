"""Shared, opt-in fixtures for native filesystem tests."""

from collections.abc import Callable
from pathlib import Path

import pytest

from tests.support.environment import home_environment


@pytest.fixture
def set_home(monkeypatch: pytest.MonkeyPatch) -> Callable[[Path], None]:
    """Point home expansion at a supplied directory for this test."""

    def apply(home: Path) -> None:
        for name, value in home_environment(home).items():
            monkeypatch.setenv(name, value)

    return apply
