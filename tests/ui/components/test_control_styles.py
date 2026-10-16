from __future__ import annotations

import asyncio

import pytest
from textual.color import Color
from textual.geometry import Region
from textual.widgets import Button, RadioButton

from ethernity.app.screens.confirm_action import ConfirmActionScreen
from ethernity.app.widgets.workflow.controls import KeyedRadioSet
from ethernity.tasks.presentation.models import ChoicePresentation
from tests.support.app import run_app_test
from tests.support.widgets import WidgetApp


def test_action_colors_and_primary_focus_survive_both_themes() -> None:
    async def run() -> None:
        for theme in ("ethernity-dark", "ethernity-light"):
            app = WidgetApp(theme=theme)
            async with run_app_test(app, size=(80, 24)) as pilot:
                await app.push_screen(
                    ConfirmActionScreen(
                        title="Restore defaults",
                        message="This replaces the current values.",
                        confirm_label="Restore",
                    )
                )
                await pilot.pause()

                cancel = app.screen.query_one("#confirm-action-cancel", Button)
                confirm = app.screen.query_one("#confirm-action-confirm", Button)
                assert cancel.variant == "primary"
                assert confirm.variant == "warning"
                assert _colors_nearly_equal(
                    confirm.styles.background,
                    Color.parse(app.current_theme.warning),
                )
                assert _colors_nearly_equal(
                    confirm.styles.color,
                    Color.parse(app.current_theme.variables["button-color-foreground"]),
                )

                cancel.focus()
                await pilot.pause()
                assert cancel.styles.text_style.bold
                assert not cancel.styles.text_style.underline

                confirm.focus()
                await pilot.pause()
                assert confirm.styles.text_style.bold
                assert not confirm.styles.text_style.underline
                assert _colors_nearly_equal(
                    confirm.styles.background,
                    Color.parse(app.current_theme.warning),
                )

    asyncio.run(run())


@pytest.mark.parametrize("theme", ["ethernity-dark", "ethernity-light"])
@pytest.mark.parametrize("size", [(120, 32), (80, 32), (80, 24), (120, 24)])
def test_radio_focus_highlights_candidate_without_changing_committed_choice(theme, size) -> None:
    async def run() -> None:
        radio = KeyedRadioSet(
            (
                ChoicePresentation("recommended_shards", "Recovery sheets", selected=True),
                ChoicePresentation("single_phrase", "Passphrase"),
            ),
            id="recovery-method",
        )
        app = WidgetApp(radio, Button("Next"), theme=theme)
        async with run_app_test(app, size=size) as pilot:
            radio.focus()
            await pilot.press("down")
            candidate = radio.query_one("RadioButton.-selected", RadioButton)
            committed = radio.query_one("RadioButton.-on", RadioButton)
            assert radio.has_focus
            assert candidate is not committed
            assert radio.selected_key == "recommended_shards"
            assert candidate.styles.background != committed.styles.background
            height = 1 if size[1] < 28 else 3
            assert candidate.region.height == height
            lines = candidate.render_lines(Region(0, 0, candidate.region.width, height))
            assert [i for i, line in enumerate(lines) if line.text.strip()] == [height // 2]
            assert all(not segment.style.underline for line in lines for segment in line)
            # The fill covers the whole row, including the space after the label.
            for line in lines:
                segments = list(line)
                assert segments[0].style.bgcolor == segments[-1].style.bgcolor
            assert candidate.styles.text_style.bold

            await pilot.click(candidate, offset=(candidate.region.width - 2, height - 1))
            assert radio.selected_key == "single_phrase"
            await pilot.press("up", "space", "tab")
            assert not radio.has_focus
            assert radio.selected_key == "recommended_shards"
            assert not candidate.styles.text_style.bold

    asyncio.run(run())


def _colors_nearly_equal(left: Color, right: Color) -> bool:
    return (
        max(
            abs(left.r - right.r),
            abs(left.g - right.g),
            abs(left.b - right.b),
        )
        <= 1
    )
