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
from types import SimpleNamespace
from unittest import mock

from rich.console import Console

from ethernity.cli.shared import ui as ui_module, ui_api
from ethernity.cli.shared.ui import renderables as ui_renderables, runtime as ui_runtime
from ethernity.cli.shared.ui.state import (
    THEME,
    UIContext,
    create_default_context,
    get_context,
    isatty,
)
from ethernity.cli.shared.ui.summary import format_auth_status


class TestUiFacade(unittest.TestCase):
    def test_ui_api_exports_match_ui_facade(self) -> None:
        self.assertEqual(set(ui_api.__all__), set(ui_module.__all__))


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
        self.assertIsNotNone(context.console)
        self.assertIsNotNone(context.console_err)

    def test_get_context_returns_singleton_instance(self) -> None:
        self.assertIs(get_context(), get_context())


class TestFormatting(unittest.TestCase):
    def test_format_auth_status_mapping(self) -> None:
        cases = (
            ("verified", False, "verified"),
            ("verified", True, "verified"),
            ("missing", False, "missing"),
            ("missing", True, "skipped (unsigned recovery)"),
            ("ignored", False, "failed (ignored during unsigned recovery)"),
            ("ignored", True, "failed (ignored during unsigned recovery)"),
            ("skipped", True, "skipped (unsigned recovery)"),
            ("invalid", True, "invalid (ignored during unsigned recovery)"),
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
        with mock.patch("ethernity.cli.shared.ui.runtime.isatty", return_value=False):
            with ui_module.status("Preparing payload...", quiet=False, context=context) as live:
                self.assertIsNone(live)
        output = out.getvalue()
        self.assertIn("Preparing payload...", output)
        self.assertNotIn("Preparing payload... \u2713", output)

    def test_plain_status_preserves_unstyled_non_tty_output(self) -> None:
        out = io.StringIO()
        console = Console(file=out, force_terminal=False)

        with mock.patch("ethernity.cli.shared.ui.runtime.isatty", return_value=False):
            with ui_runtime.plain_status(
                "Rendering document...",
                console=console,
            ) as live:
                self.assertIsNone(live)

        self.assertEqual(out.getvalue().strip(), "Rendering document...")

    def test_plain_status_quiet_has_no_output(self) -> None:
        out = io.StringIO()
        with ui_runtime.plain_status(
            "Rendering document...",
            quiet=True,
            console=Console(file=out, force_terminal=False),
        ) as live:
            self.assertIsNone(live)
        self.assertEqual(out.getvalue(), "")


class TestUIHelpers(unittest.TestCase):
    def _context(self, *, force_terminal: bool = False) -> UIContext:
        return UIContext(
            theme=THEME,
            console=Console(file=io.StringIO(), force_terminal=force_terminal, theme=THEME),
            console_err=Console(file=io.StringIO(), force_terminal=force_terminal, theme=THEME),
            animations_enabled=True,
        )

    def test_resolve_context_fallbacks(self) -> None:
        context = self._context()
        self.assertIs(ui_runtime._resolve_context(context), context)
        self.assertIs(ui_runtime._resolve_context(None), ui_runtime.DEFAULT_CONTEXT)

    def test_configure_ui_toggles_flags(self) -> None:
        context = self._context(force_terminal=True)
        ui_module.configure_ui(no_color=True, no_animations=True, context=context)
        self.assertFalse(context.animations_enabled)
        self.assertTrue(context.console.no_color)
        self.assertTrue(context.console_err.no_color)

    def test_progress_quiet_returns_none(self) -> None:
        with ui_module.progress(quiet=True) as prog:
            self.assertIsNone(prog)

    @mock.patch("ethernity.cli.shared.ui.runtime.isatty", return_value=True)
    def test_progress_animated_uses_full_columns(self, _isatty: mock.MagicMock) -> None:
        context = self._context(force_terminal=True)
        context.animations_enabled = True
        with ui_module.progress(quiet=False, context=context) as prog:
            self.assertIsNotNone(prog)
            self.assertEqual(len(prog.columns), 5)

    @mock.patch("ethernity.cli.shared.ui.runtime.isatty", return_value=True)
    def test_progress_nonanimated_uses_single_text_column(self, _isatty: mock.MagicMock) -> None:
        context = self._context(force_terminal=True)
        context.animations_enabled = False
        with ui_module.progress(quiet=False, context=context) as prog:
            self.assertIsNotNone(prog)
            self.assertEqual(len(prog.columns), 1)

    def test_status_quiet_returns_none(self) -> None:
        with ui_module.status("Reading...", quiet=True) as live:
            self.assertIsNone(live)

    @mock.patch("ethernity.cli.shared.ui.runtime.isatty", return_value=True)
    def test_status_animated_handles_flush_errors(self, _isatty: mock.MagicMock) -> None:
        context = self._context(force_terminal=True)
        context.animations_enabled = True
        context.console.file = mock.MagicMock()
        context.console.file.flush.side_effect = OSError("no flush")
        live = mock.MagicMock()
        live_cm = mock.MagicMock()
        live_cm.__enter__.return_value = live
        live_cm.__exit__.return_value = False
        with mock.patch("ethernity.cli.shared.ui.runtime.Live", return_value=live_cm):
            with ui_module.status("Preparing...", quiet=False, context=context) as status_live:
                self.assertIs(status_live, live)
        live.update.assert_called_once()

    @mock.patch("ethernity.cli.shared.ui.runtime.isatty", return_value=True)
    def test_status_animated_is_not_transient(self, _isatty: mock.MagicMock) -> None:
        context = self._context(force_terminal=True)
        context.animations_enabled = True
        context.console.file = mock.MagicMock()
        live = mock.MagicMock()
        live_cm = mock.MagicMock()
        live_cm.__enter__.return_value = live
        live_cm.__exit__.return_value = False
        with mock.patch("ethernity.cli.shared.ui.runtime.Live", return_value=live_cm) as live_ctor:
            with ui_module.status("Preparing...", quiet=False, context=context) as status_live:
                self.assertIs(status_live, live)
        self.assertFalse(live_ctor.call_args.kwargs["transient"])
        live.update.assert_called_once()

    def test_build_table_and_panel_helpers(self) -> None:
        kv = ui_module.build_kv_table([("A", "1")], title="Meta")
        review = ui_module.build_review_table([("Inputs", None), ("Main", "2")])
        actions = ui_module.build_action_list(["Do this"])
        list_table = ui_module.build_list_table("Files", ["a.txt"])
        pnl = ui_module.panel("Title", "Body")
        self.assertEqual(kv.title, "Meta")
        self.assertEqual(len(kv.rows), 1)
        self.assertEqual(len(review.rows), 2)
        self.assertEqual(len(actions.rows), 1)
        self.assertEqual(list_table.title, "Files")
        self.assertEqual(pnl.title, "Title")

    def test_print_completion_panel_respects_quiet_and_use_err(self) -> None:
        with mock.patch.object(ui_renderables.console, "print") as out_print:
            with mock.patch.object(ui_renderables.console_err, "print") as err_print:
                ui_module.print_completion_panel("Done", ["one"], quiet=True)
                ui_module.print_completion_panel("Done", ["one"], quiet=False, use_err=True)
        out_print.assert_not_called()
        err_print.assert_called_once()

    def test_build_outputs_tree_and_recovered_tree(self) -> None:
        tree = ui_module.build_outputs_tree(
            "qr.pdf",
            "recovery.txt",
            ["shard-1.pdf", "shard-2.pdf"],
            ["signing-1.pdf"],
            kit_index_path="kit-index.pdf",
        )
        out = io.StringIO()
        Console(file=out, force_terminal=False, theme=THEME).print(tree)
        rendered = out.getvalue()
        self.assertIn("Recovery kit index", rendered)
        self.assertIn("shard-1.pdf", rendered)
        self.assertIn("Signing authority shard documents", rendered)

        self.assertIsNone(ui_module.build_recovered_tree([], output_path=None))
        single = ui_module.build_recovered_tree([(SimpleNamespace(path="a.txt"), b"x")], "a.txt")
        self.assertIsNotNone(single)
        single_dir = ui_module.build_recovered_tree(
            [(SimpleNamespace(path="a.txt"), b"x")],
            "out-dir",
            single_entry_output_is_directory=True,
        )
        self.assertIsNotNone(single_dir)
        multi = ui_module.build_recovered_tree(
            [
                (SimpleNamespace(path="a.txt"), b"x"),
                (SimpleNamespace(path="b.txt"), b"y"),
            ],
            "out-dir",
        )
        self.assertIsNotNone(multi)
        out = io.StringIO()
        Console(file=out, force_terminal=False, theme=THEME).print(multi)
        self.assertIn("out-dir", out.getvalue())
        out = io.StringIO()
        Console(file=out, force_terminal=False, theme=THEME).print(single_dir)
        self.assertIn("a.txt", out.getvalue())


if __name__ == "__main__":
    unittest.main()
