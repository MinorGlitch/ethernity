from __future__ import annotations

import asyncio

import pytest
from rich.text import Text
from textual.app import ComposeResult
from textual.widgets import Input, OptionList

from ethernity.app.styling import StyledApp
from ethernity.app.widgets.form import FormSelect


class DropdownApp(StyledApp):
    def __init__(self, *, allow_blank: bool) -> None:
        super().__init__()
        self.allow_blank = allow_blank

    def compose(self) -> ComposeResult:
        yield FormSelect(
            [("Alpha", "a"), ("Beta", "b"), ("Gamma", "c")],
            allow_blank=self.allow_blank,
            id="choice",
        )
        yield Input(id="next-field")


@pytest.mark.parametrize("allow_blank", [False, True])
def test_dropdown_padding_is_highlighted_clickable_and_survives_updates(allow_blank: bool) -> None:
    async def run() -> None:
        app = DropdownApp(allow_blank=allow_blank)
        async with app.run_test(size=(80, 24)) as pilot:
            field = app.query_one(FormSelect)
            await pilot.press("enter")
            overlay = field.query_one(OptionList)
            count = 4 if allow_blank else 3
            assert overlay.option_count == count
            assert overlay.virtual_size.height == count * 3
            await pilot.press("home")
            selected_background = next(iter(overlay.render_line(1))).style.bgcolor
            for y in range(count * 3):
                strip = overlay.render_line(y)
                if y % 3 != 1:
                    assert not strip.text.strip()
                for segment in strip:
                    assert segment.style.meta["option"] == y // 3
                    if y < 3:
                        assert segment.style.bgcolor == selected_background
            # Both the top and bottom padding of Beta select Beta, not an adjacent option.
            beta_index = 2 if allow_blank else 1
            for row in (0, 2):
                await pilot.click(overlay, offset=(3, overlay.gutter.top + beta_index * 3 + row))
                assert not field.expanded
                assert field.value == "b"
                await pilot.press("enter")
            await pilot.press("end", "enter")
            assert field.value == "c"
            assert not field.expanded

            options = [(Text("New alpha", style="bold"), "x"), ("New beta", "y")]
            field.set_options(options)
            await pilot.pause()
            await pilot.press("enter", "n", "e", "w", "space", "b")
            assert overlay.option_count == (3 if allow_blank else 2)
            assert overlay.virtual_size.height == overlay.option_count * 3
            assert str(overlay.get_option_at_index(overlay.highlighted).prompt) == "New beta"
            await pilot.press("enter")
            assert field.value == "y"
            await pilot.press("enter", "shift+tab")
            assert not field.expanded
            assert app.focused is app.query_one("#next-field")

    asyncio.run(run())


def test_long_dropdown_choices_wrap_and_scroll_without_clipping() -> None:
    async def run() -> None:
        app = DropdownApp(allow_blank=False)
        async with app.run_test(size=(40, 20)) as pilot:
            field = app.query_one(FormSelect)
            labels = [
                f"Choice {index} with a description that wraps onto another line"
                for index in range(12)
            ]
            field.set_options([(label, str(index)) for index, label in enumerate(labels)])
            await pilot.pause()
            await pilot.press("enter", "end")
            overlay = field.query_one(OptionList)
            assert overlay.highlighted == 11
            assert overlay.scroll_y > 0
            assert app.screen.region.contains_region(overlay.region)
            painted = " ".join(
                overlay.render_line(y).text.strip() for y in range(overlay.content_size.height)
            )
            assert labels[-1] in painted
            await pilot.press("enter")
            assert field.value == "11"
            current = field.query_one("SelectCurrent #label")
            assert current.region.height == 1
            assert current.render_line(0).text.rstrip().endswith("…")

    asyncio.run(run())
