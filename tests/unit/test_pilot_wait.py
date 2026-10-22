import asyncio
from types import SimpleNamespace
from typing import cast

import pytest
from textual.pilot import Pilot

from tests.support import pilot as pilot_support


@pytest.mark.parametrize("ready_after", [1, 2, None])
def test_wait_observes_settled_state_before_reporting_timeout(monkeypatch, ready_after) -> None:
    elapsed = 0.0
    pauses = 0

    async def pause(delay=None) -> None:
        nonlocal elapsed, pauses
        pauses += 1
        if pauses == (ready_after or 2):
            elapsed = 6.0

    monkeypatch.setattr(pilot_support, "monotonic", lambda: elapsed)
    pilot = cast(
        Pilot,
        SimpleNamespace(pause=pause, app=SimpleNamespace(screen=SimpleNamespace(focused=None))),
    )

    async def run() -> None:
        await pilot_support.wait_for_condition(
            pilot,
            lambda: ready_after is not None and pauses >= ready_after,
            "rendered result",
            timeout=5.0,
        )

    if ready_after is None:
        with pytest.raises(AssertionError, match="Timed out waiting for rendered result"):
            asyncio.run(run())
    else:
        asyncio.run(run())
