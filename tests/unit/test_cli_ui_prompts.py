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

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import questionary
from rich.console import Console

from ethernity.cli.ui import prompts as prompts_module
from ethernity.cli.ui.state import THEME, UIContext


class _Ask:
    def __init__(self, values):
        self._values = list(values)

    def ask(self):
        if not self._values:
            return None
        return self._values.pop(0)


def _context() -> UIContext:
    return UIContext(
        theme=THEME,
        console=Console(
            file=SimpleNamespace(write=lambda *_: None, flush=lambda: None), theme=THEME
        ),
        console_err=Console(
            file=SimpleNamespace(write=lambda *_: None, flush=lambda: None), theme=THEME
        ),
        animations_enabled=True,
    )


class TestPromptPrimitives(unittest.TestCase):
    def test_print_prompt_header_compact_suppresses_repeated_headers(self) -> None:
        context = _context()
        context.compact_prompt_headers = True
        context.stage_prompt_count = 0
        context.console.print = mock.MagicMock()
        prompts_module.print_prompt_header("First", "hint", context=context)
        prompts_module.print_prompt_header("Second", "hint", context=context)
        self.assertEqual(context.stage_prompt_count, 2)
        self.assertEqual(context.console.print.call_count, 2)

    def test_print_prompt_header_non_compact_prints_each_time(self) -> None:
        context = _context()
        context.compact_prompt_headers = False
        context.console.print = mock.MagicMock()
        prompts_module.print_prompt_header("First", None, context=context)
        prompts_module.print_prompt_header("Second", None, context=context)
        self.assertEqual(context.console.print.call_count, 2)

    @mock.patch("ethernity.cli.ui.prompts.print_prompt_header")
    def test_prompt_optional_secret(self, print_prompt_header: mock.MagicMock) -> None:
        with mock.patch(
            "ethernity.cli.ui.prompts.questionary.password",
            return_value=_Ask([""]),
        ):
            self.assertIsNone(prompts_module.prompt_optional_secret("Secret?"))
        with mock.patch(
            "ethernity.cli.ui.prompts.questionary.password",
            return_value=_Ask(["value"]),
        ):
            self.assertEqual(prompts_module.prompt_optional_secret("Secret?"), "value")
        with mock.patch(
            "ethernity.cli.ui.prompts.questionary.password",
            return_value=_Ask([None]),
        ):
            with self.assertRaises(KeyboardInterrupt):
                prompts_module.prompt_optional_secret("Secret?")
        self.assertGreaterEqual(print_prompt_header.call_count, 3)

    def test_prompt_required_secret_retries_and_accepts(self) -> None:
        context = _context()
        context.console_err.print = mock.MagicMock()
        with mock.patch(
            "ethernity.cli.ui.prompts.questionary.password",
            return_value=_Ask(["", "secret"]),
        ):
            value = prompts_module.prompt_required_secret("Secret?", context=context)
        self.assertEqual(value, "secret")
        context.console_err.print.assert_called_once()

    def test_prompt_required_secret_keyboard_interrupt(self) -> None:
        with mock.patch("ethernity.cli.ui.prompts.questionary.password", return_value=_Ask([None])):
            with self.assertRaises(KeyboardInterrupt):
                prompts_module.prompt_required_secret("Secret?")

    @mock.patch("ethernity.cli.ui.prompts.prompt_choice_list", return_value="x")
    def test_prompt_choice_delegates_to_choice_list(
        self,
        prompt_choice_list: mock.MagicMock,
    ) -> None:
        value = prompts_module.prompt_choice("Pick", {"x": "X"}, default="x")
        self.assertEqual(value, "x")
        prompt_choice_list.assert_called_once()

    def test_prompt_yes_no(self) -> None:
        with mock.patch("ethernity.cli.ui.prompts.questionary.confirm", return_value=_Ask([True])):
            self.assertTrue(prompts_module.prompt_yes_no("Continue?", default=True))
        with mock.patch("ethernity.cli.ui.prompts.questionary.confirm", return_value=_Ask([None])):
            with self.assertRaises(KeyboardInterrupt):
                prompts_module.prompt_yes_no("Continue?", default=False)

    def test_prompt_optional_required_and_multiline(self) -> None:
        with mock.patch(
            "ethernity.cli.ui.prompts.questionary.text", return_value=_Ask([" value "])
        ):
            self.assertEqual(prompts_module.prompt_optional("Name"), "value")
        with mock.patch("ethernity.cli.ui.prompts.questionary.text", return_value=_Ask(["  "])):
            self.assertIsNone(prompts_module.prompt_optional("Name"))
        with mock.patch("ethernity.cli.ui.prompts.questionary.text", return_value=_Ask([None])):
            with self.assertRaises(KeyboardInterrupt):
                prompts_module.prompt_optional("Name")

        context = _context()
        context.console_err.print = mock.MagicMock()
        with mock.patch(
            "ethernity.cli.ui.prompts.questionary.text", return_value=_Ask(["", "ready"])
        ):
            self.assertEqual(prompts_module.prompt_required("Value", context=context), "ready")
        context.console_err.print.assert_called()

        with mock.patch(
            "ethernity.cli.ui.prompts.questionary.text",
            return_value=_Ask(["one\ntwo", "-"]),
        ):
            items = prompts_module.prompt_multiline("Lines", stop_on_dash=True)
        self.assertEqual(items, ["one", "two", "-"])

    def test_prompt_int_validation(self) -> None:
        context = _context()
        context.console_err.print = mock.MagicMock()
        with mock.patch(
            "ethernity.cli.ui.prompts.questionary.text",
            return_value=_Ask(["", "abc", "0", "11", "5"]),
        ):
            value = prompts_module.prompt_int("Count", minimum=1, maximum=10, context=context)
        self.assertEqual(value, 5)
        self.assertGreaterEqual(context.console_err.print.call_count, 4)


class TestChoiceAndPickerInternals(unittest.TestCase):
    def test_select_without_default_highlight_rejects_empty_choices(self) -> None:
        with self.assertRaisesRegex(ValueError, "list of choices needs to be provided"):
            prompts_module._select_without_default_highlight("Pick", choices=[], default=None)

    def test_select_without_default_highlight_returns_question(self) -> None:
        with mock.patch("ethernity.cli.ui.prompts.common.create_inquirer_layout"):
            with mock.patch("ethernity.cli.ui.prompts.Application", return_value=mock.MagicMock()):
                question = prompts_module._select_without_default_highlight(
                    "Pick",
                    choices=[questionary.Choice(title="A", value="a")],
                    default="a",
                )
        self.assertIsNotNone(question)

    @mock.patch(
        "ethernity.cli.ui.prompts._select_without_default_highlight", return_value=_Ask([None])
    )
    def test_prompt_choice_list_default_fallback(
        self,
        _select_without_default_highlight: mock.MagicMock,
    ) -> None:
        value = prompts_module.prompt_choice_list([("a", "A")], default="a")
        self.assertEqual(value, "a")
        with self.assertRaises(KeyboardInterrupt):
            prompts_module.prompt_choice_list([("a", "A")], default=None)

    def test_list_picker_entries_filters_and_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".hidden").write_text("x", encoding="utf-8")
            (root / "file.txt").write_text("x", encoding="utf-8")
            (root / "dir").mkdir()
            entries = prompts_module._list_picker_entries(
                str(root),
                allow_files=True,
                allow_dirs=True,
                include_hidden=False,
            )
            values = {label for _, label in entries}
            self.assertIn("file.txt", values)
            self.assertIn("dir/", values)
            self.assertNotIn(".hidden", values)

            with self.assertRaisesRegex(ValueError, "No selectable entries"):
                prompts_module._list_picker_entries(
                    str(root),
                    allow_files=False,
                    allow_dirs=False,
                    include_hidden=False,
                )

            with self.assertRaisesRegex(ValueError, "dir not found"):
                prompts_module._list_picker_entries(
                    str(root / "missing"),
                    allow_files=True,
                    allow_dirs=True,
                    include_hidden=False,
                )

    def test_list_picker_entries_empty_error_is_actionable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(
                ValueError,
                "Choose another directory or switch to manual entry",
            ):
                prompts_module._list_picker_entries(
                    str(root),
                    allow_files=False,
                    allow_dirs=False,
                    include_hidden=False,
                )

    @mock.patch("ethernity.cli.ui.prompts.prompt_optional_path", side_effect=[".", ".", "."])
    @mock.patch(
        "ethernity.cli.ui.prompts.prompt_choice",
        side_effect=["select", "select", "manual"],
    )
    def test_run_picker_flow_retry_then_manual(
        self,
        _prompt_choice: mock.MagicMock,
        _prompt_optional_path: mock.MagicMock,
    ) -> None:
        context = _context()
        context.console_err.print = mock.MagicMock()
        select_func = mock.MagicMock(side_effect=[ValueError("bad dir"), "selected"])
        manual_func = mock.MagicMock(return_value="manual")

        value = prompts_module._run_picker_flow(
            selection_prompt="mode",
            selection_help_text=None,
            manual_label="manual",
            directory_prompt="dir",
            directory_help_text="help",
            picker_help_text="picker",
            context=context,
            select_func=select_func,
            manual_func=manual_func,
        )
        self.assertEqual(value, "selected")

        value2 = prompts_module._run_picker_flow(
            selection_prompt="mode",
            selection_help_text=None,
            manual_label="manual",
            directory_prompt="dir",
            directory_help_text="help",
            picker_help_text="picker",
            context=context,
            select_func=select_func,
            manual_func=manual_func,
        )
        self.assertEqual(value2, "manual")
        manual_func.assert_called_once()

    @mock.patch("ethernity.cli.ui.prompts.prompt_optional_path", return_value=None)
    @mock.patch("ethernity.cli.ui.prompts.prompt_choice", return_value="select")
    def test_run_picker_flow_uses_last_picker_dir_default(
        self,
        _prompt_choice: mock.MagicMock,
        _prompt_optional_path: mock.MagicMock,
    ) -> None:
        context = _context()
        context.last_picker_dir = "/tmp/last-picker"
        select_func = mock.MagicMock(return_value="/tmp/last-picker/chosen.txt")
        value = prompts_module._run_picker_flow(
            selection_prompt="mode",
            selection_help_text=None,
            manual_label="manual",
            directory_prompt="dir",
            directory_help_text="help",
            picker_help_text="picker",
            context=context,
            select_func=select_func,
            manual_func=mock.MagicMock(),
        )
        self.assertEqual(value, "/tmp/last-picker/chosen.txt")
        select_func.assert_called_once_with("/tmp/last-picker")

    @mock.patch("ethernity.cli.ui.prompts.prompt_optional_path", return_value=".")
    @mock.patch("ethernity.cli.ui.prompts.prompt_choice", return_value="select")
    def test_run_picker_flow_updates_last_picker_dir_after_select(
        self,
        _prompt_choice: mock.MagicMock,
        _prompt_optional_path: mock.MagicMock,
    ) -> None:
        context = _context()
        context.last_picker_dir = "."
        select_func = mock.MagicMock(return_value="/tmp/out/file.txt")
        prompts_module._run_picker_flow(
            selection_prompt="mode",
            selection_help_text=None,
            manual_label="manual",
            directory_prompt="dir",
            directory_help_text="help",
            picker_help_text="picker",
            context=context,
            select_func=select_func,
            manual_func=mock.MagicMock(),
        )
        self.assertEqual(context.last_picker_dir, "/tmp/out")

    @mock.patch("ethernity.cli.ui.prompts.prompt_choice", return_value="manual")
    def test_run_picker_flow_updates_last_picker_dir_after_manual(
        self,
        _prompt_choice: mock.MagicMock,
    ) -> None:
        context = _context()
        manual_func = mock.MagicMock(return_value="/tmp/manual/path.txt")
        prompts_module._run_picker_flow(
            selection_prompt="mode",
            selection_help_text=None,
            manual_label="manual",
            directory_prompt="dir",
            directory_help_text="help",
            picker_help_text="picker",
            context=context,
            select_func=mock.MagicMock(),
            manual_func=manual_func,
        )
        self.assertEqual(context.last_picker_dir, "/tmp/manual")

    @mock.patch("ethernity.cli.ui.prompts.prompt_choice_list", return_value="chosen")
    def test_prompt_select_entries_single(
        self,
        prompt_choice_list: mock.MagicMock,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.txt"
            path.write_text("x", encoding="utf-8")
            value = prompts_module._prompt_select_entries(
                "Pick one",
                directory=tmp,
                allow_files=True,
                allow_dirs=False,
                include_hidden=False,
                help_text="help",
                multi=False,
                context=_context(),
            )
        self.assertEqual(value, "chosen")
        prompt_choice_list.assert_called_once()

    def test_prompt_select_entries_multi_retries_on_empty(self) -> None:
        context = _context()
        context.console.print = mock.MagicMock()
        context.console_err.print = mock.MagicMock()
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.txt").write_text("x", encoding="utf-8")
            checkbox = _Ask([[], ["ok"]])
            with mock.patch("ethernity.cli.ui.prompts.questionary.checkbox", return_value=checkbox):
                values = prompts_module._prompt_select_entries(
                    "Pick many",
                    directory=tmp,
                    allow_files=True,
                    allow_dirs=False,
                    include_hidden=False,
                    help_text="help",
                    multi=True,
                    context=context,
                )
        self.assertEqual(values, ["ok"])
        context.console_err.print.assert_called()

    @mock.patch("ethernity.cli.ui.prompts._prompt_select_entries", return_value=["a", "b"])
    def test_prompt_select_paths_wrapper(self, _prompt_select_entries: mock.MagicMock) -> None:
        values = prompts_module.prompt_select_paths("Pick", directory=".")
        self.assertEqual(values, ["a", "b"])

    @mock.patch("ethernity.cli.ui.prompts._prompt_select_entries", return_value="a")
    def test_prompt_select_path_wrapper(self, _prompt_select_entries: mock.MagicMock) -> None:
        value = prompts_module.prompt_select_path("Pick", directory=".")
        self.assertEqual(value, "a")

    @mock.patch("ethernity.cli.ui.prompts._run_picker_flow", return_value="picked")
    def test_prompt_path_with_picker_delegates(self, run_picker_flow: mock.MagicMock) -> None:
        value = prompts_module.prompt_path_with_picker("Path", kind="file")
        self.assertEqual(value, "picked")
        run_picker_flow.assert_called_once()

    @mock.patch("ethernity.cli.ui.prompts._run_picker_flow", return_value=None)
    def test_prompt_optional_path_with_picker_delegates(
        self,
        run_picker_flow: mock.MagicMock,
    ) -> None:
        value = prompts_module.prompt_optional_path_with_picker("Path", kind="file")
        self.assertIsNone(value)
        run_picker_flow.assert_called_once()


class TestPathValidationFlows(unittest.TestCase):
    def test_validate_path_cases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file_path = root / "a.txt"
            file_path.write_text("x", encoding="utf-8")
            dir_path = root / "d"
            dir_path.mkdir()

            self.assertIsNone(prompts_module.validate_path(str(file_path), kind="file"))
            self.assertIsNone(prompts_module.validate_path(str(dir_path), kind="dir"))
            self.assertIn(
                "not a directory", prompts_module.validate_path(str(file_path), kind="dir") or ""
            )
            self.assertIn(
                "not a file", prompts_module.validate_path(str(dir_path), kind="file") or ""
            )
            self.assertIn(
                "not found",
                prompts_module.validate_path(str(root / "missing"), kind="path") or "",
            )
            self.assertIsNone(
                prompts_module.validate_path(str(root / "new"), kind="path", allow_new=True)
            )

    @mock.patch("ethernity.cli.ui.prompts.validate_path", side_effect=["bad", None, None, None])
    @mock.patch("ethernity.cli.ui.prompts.prompt_optional", side_effect=[None, "value"])
    @mock.patch("ethernity.cli.ui.prompts.prompt_required", side_effect=["-", "bad", "good"])
    def test_prompt_path_required_optional_and_stdin(
        self,
        _prompt_required: mock.MagicMock,
        _prompt_optional: mock.MagicMock,
        _validate_path: mock.MagicMock,
    ) -> None:
        context = _context()
        context.console_err.print = mock.MagicMock()
        self.assertEqual(
            prompts_module._prompt_path(
                "Path",
                kind="file",
                required=True,
                help_text=None,
                allow_stdin=True,
                context=context,
            ),
            "-",
        )
        self.assertEqual(
            prompts_module._prompt_path(
                "Path",
                kind="file",
                required=True,
                help_text=None,
                context=context,
            ),
            "good",
        )
        self.assertIsNone(
            prompts_module._prompt_path(
                "Path",
                kind="file",
                required=False,
                help_text=None,
                context=context,
            )
        )
        self.assertEqual(
            prompts_module._prompt_path(
                "Path",
                kind="file",
                required=False,
                help_text=None,
                context=context,
            ),
            "value",
        )

    @mock.patch("ethernity.cli.ui.prompts._prompt_path", return_value="x")
    def test_required_optional_path_wrappers(self, _prompt_path: mock.MagicMock) -> None:
        self.assertEqual(prompts_module.prompt_required_path("P", kind="file"), "x")
        self.assertEqual(prompts_module.prompt_optional_path("P", kind="file"), "x")
        _prompt_path.return_value = None
        with self.assertRaises(KeyboardInterrupt):
            prompts_module.prompt_required_path("P", kind="file")

    def test_prompt_required_paths_validation_loops(self) -> None:
        context = _context()
        context.console_err.print = mock.MagicMock()
        with mock.patch(
            "ethernity.cli.ui.prompts.prompt_multiline",
            side_effect=[[], ["-"], ["a.txt", "-"], ["bad"], ["ok"]],
        ):
            with mock.patch(
                "ethernity.cli.ui.prompts.validate_path",
                side_effect=["broken", None],
            ):
                values = prompts_module.prompt_required_paths(
                    "Paths",
                    kind="file",
                    allow_stdin=False,
                    context=context,
                )
        self.assertEqual(values, ["ok"])
        self.assertGreaterEqual(context.console_err.print.call_count, 3)

        with mock.patch("ethernity.cli.ui.prompts.prompt_multiline", return_value=["-"]):
            values = prompts_module.prompt_required_paths(
                "Paths",
                kind="file",
                allow_stdin=True,
                context=_context(),
            )
        self.assertEqual(values, ["-"])

    @mock.patch("ethernity.cli.ui.prompts._run_picker_flow", return_value=["a.txt"])
    def test_prompt_paths_with_picker_delegates(self, run_picker_flow: mock.MagicMock) -> None:
        values = prompts_module.prompt_paths_with_picker("Enter paths")
        self.assertEqual(values, ["a.txt"])
        run_picker_flow.assert_called_once()


if __name__ == "__main__":
    unittest.main()
