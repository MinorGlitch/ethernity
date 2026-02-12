# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>.

import io
import sys
import unittest
from unittest import mock

from rich.console import Console

from ethernity.cli import ui as ui_module
from ethernity.cli.ui.state import (
    THEME,
    UIContext,
    create_default_context,
    format_hint,
    get_context,
    isatty,
)
from ethernity.cli.ui.summary import format_auth_status


class TestIsatty(unittest.TestCase):
    def test_stream_isatty_passthrough(self) -> None:
        for expected in (True, False):
            with self.subTest(expected=expected):
                stream = mock.MagicMock()
                stream.isatty.return_value = expected
                self.assertEqual(isatty(stream, fallback=sys.stdout), expected)

    def test_stream_isatty_errors_return_false(self) -> None:
        side_effects = (
            OSError("not available"),
            ValueError("closed"),
            AttributeError("missing"),
        )
        for side_effect in side_effects:
            with self.subTest(side_effect=type(side_effect).__name__):
                stream = mock.MagicMock()
                stream.isatty.side_effect = side_effect
                self.assertFalse(isatty(stream, fallback=sys.stdout))

    def test_none_stream_uses_fallback_isatty(self) -> None:
        for fallback_value in (True, False):
            with self.subTest(fallback_value=fallback_value):
                fallback = mock.MagicMock()
                fallback.isatty.return_value = fallback_value
                self.assertEqual(isatty(None, fallback=fallback), fallback_value)

    def test_none_stream_without_fallback_isatty_returns_false(self) -> None:
        self.assertFalse(isatty(None, fallback=object()))

    def test_stringio_is_not_tty(self) -> None:
        self.assertFalse(isatty(io.StringIO(), fallback=sys.stdout))


class TestContextState(unittest.TestCase):
    def test_create_default_context_has_expected_defaults(self) -> None:
        context = create_default_context()
        self.assertEqual(context.theme, THEME)
        self.assertTrue(context.animations_enabled)
        self.assertIsNone(context.wizard_state)
        self.assertIsNotNone(context.console)
        self.assertIsNotNone(context.console_err)

    def test_get_context_returns_singleton_instance(self) -> None:
        self.assertIs(get_context(), get_context())


class TestFormatting(unittest.TestCase):
    def test_format_hint_passthrough(self) -> None:
        for text in ("Press Enter to continue", ""):
            with self.subTest(text=text):
                self.assertEqual(str(format_hint(text)), text)

    def test_format_auth_status_mapping(self) -> None:
        cases = (
            ("verified", False, "verified"),
            ("verified", True, "verified"),
            ("missing", False, "missing"),
            ("missing", True, "skipped (--skip-auth-check)"),
            ("ignored", False, "failed (ignored due to --skip-auth-check)"),
            ("ignored", True, "failed (ignored due to --skip-auth-check)"),
            ("skipped", True, "skipped (--skip-auth-check)"),
            ("invalid", True, "invalid (ignored due to --skip-auth-check)"),
            ("custom-status", False, "custom-status"),
        )
        for status, allow_unsigned, expected in cases:
            with self.subTest(status=status, allow_unsigned=allow_unsigned):
                self.assertEqual(
                    format_auth_status(status, allow_unsigned=allow_unsigned),
                    expected,
                )


class TestTheme(unittest.TestCase):
    def test_theme_has_required_styles(self) -> None:
        required_styles = {
            "title",
            "subtitle",
            "accent",
            "success",
            "warning",
            "error",
            "rule",
            "panel",
            "muted",
        }
        self.assertTrue(required_styles.issubset(set(THEME.styles)))
        for style in required_styles:
            self.assertTrue(str(THEME.styles[style]))


class TestStatusOutput(unittest.TestCase):
    def test_status_non_tty_uses_plain_message(self) -> None:
        out = io.StringIO()
        context = UIContext(
            theme=THEME,
            console=Console(file=out, force_terminal=False, theme=THEME),
            console_err=Console(file=io.StringIO(), force_terminal=False, theme=THEME, stderr=True),
            animations_enabled=True,
        )
        with mock.patch("ethernity.cli.ui.isatty", return_value=False):
            with ui_module.status("Preparing payload...", quiet=False, context=context) as live:
                self.assertIsNone(live)
        output = out.getvalue()
        self.assertIn("Preparing payload...", output)
        self.assertNotIn("Preparing payload... \u2713", output)


if __name__ == "__main__":
    unittest.main()
