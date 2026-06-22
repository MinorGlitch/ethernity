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

from ethernity.cli.shared.ui import (
    picker as picker_module,
    prompts as prompts_module,
    prompts_core as prompts_core_module,
    workspace as workspace_module,
)
from ethernity.cli.shared.ui.state import THEME, UIContext


class _Ask:
    def __init__(self, values):
        self._values = list(values)

    def ask(self):
        if not self._values:
            return None
        return self._values.pop(0)

    def unsafe_ask(self):
        return self.ask()


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
    def test_ask_question_prefers_unsafe_ask(self) -> None:
        question = mock.Mock()
        question.unsafe_ask.return_value = "value"
        question.ask.return_value = "fallback"
        self.assertEqual(prompts_core_module._ask_question(question), "value")
        question.unsafe_ask.assert_called_once_with()
        question.ask.assert_not_called()

    def test_print_prompt_header_screen_mode_keeps_help_text_lightweight(self) -> None:
        context = _context()
        context.screen_mode = True
        context.compact_prompt_headers = True
        context.current_stage_title = "Input"
        context.current_stage_help_text = "Stage hint"
        context.stage_prompt_count = 0
        context.console.print = mock.MagicMock()
        prompts_module.print_prompt_header("First", "hint", context=context)
        prompts_module.print_prompt_header("Second", "hint", context=context)
        self.assertEqual(context.stage_prompt_count, 2)
        self.assertEqual(context.console.print.call_count, 4)
        first_prompt = context.console.print.call_args_list[0].args[0]
        self.assertEqual(getattr(first_prompt, "plain", ""), "First\n")

    @mock.patch("ethernity.cli.shared.ui.prompts_core.clear_screen")
    def test_print_prompt_header_screen_mode_preserves_first_rendered_home_screen(
        self,
        clear_screen: mock.MagicMock,
    ) -> None:
        context = _context()
        context.screen_mode = True
        context.console.print = mock.MagicMock()
        prompts_module.print_prompt_header("First", "hint", context=context)
        clear_screen.assert_not_called()
        prompts_module.print_prompt_header("Second", "hint", context=context)
        clear_screen.assert_called_once_with(context=context)

    @mock.patch("ethernity.cli.shared.ui.prompts_core.clear_screen")
    def test_print_prompt_header_screen_mode_redraws_first_prompt_inside_stage(
        self,
        clear_screen: mock.MagicMock,
    ) -> None:
        context = _context()
        context.screen_mode = True
        context.current_stage_title = "Input"
        context.console.print = mock.MagicMock()
        prompts_module.print_prompt_header("First", "hint", context=context)
        clear_screen.assert_not_called()

    def test_print_prompt_header_screen_mode_uses_stage_title_when_no_help_text(self) -> None:
        context = _context()
        context.screen_mode = True
        context.compact_prompt_headers = True
        context.current_stage_title = "Input"
        context.stage_prompt_count = 1
        context.console.print = mock.MagicMock()
        prompts_module.print_prompt_header("Second", None, context=context)
        self.assertEqual(context.stage_prompt_count, 2)
        printed = [
            str(call.args[0]) if call.args else "" for call in context.console.print.call_args_list
        ]
        self.assertTrue(any("Input" in entry for entry in printed))

    def test_print_prompt_header_screen_mode_renders_dense_substep_context(self) -> None:
        context = _context()
        context.screen_mode = True
        context.compact_prompt_headers = True
        context.current_stage_title = "Input"
        context.current_stage_density = "dense"
        context.current_substep_title = "Choose source"
        context.current_substep_help_text = "Pick the backup artifact you already have."
        context.console.print = mock.MagicMock()

        prompts_module.print_prompt_header(
            "How do you want to provide the backup",
            None,
            context=context,
        )

        printed = [
            getattr(call.args[0], "plain", str(call.args[0]))
            for call in context.console.print.call_args_list
            if call.args
        ]
        self.assertTrue(any("Choose source" in entry for entry in printed))
        self.assertEqual(context.console.print.call_count, 3)

    def test_print_prompt_header_non_compact_prints_each_time(self) -> None:
        context = _context()
        context.compact_prompt_headers = False
        context.console.print = mock.MagicMock()
        prompts_module.print_prompt_header("First", None, context=context)
        prompts_module.print_prompt_header("Second", None, context=context)
        self.assertEqual(context.console.print.call_count, 2)

    @mock.patch("ethernity.cli.shared.ui.prompts_core.print_prompt_header")
    def test_prompt_optional_secret(self, print_prompt_header: mock.MagicMock) -> None:
        with mock.patch(
            "ethernity.cli.shared.ui.prompts_core.questionary.password",
            return_value=_Ask([""]),
        ):
            self.assertIsNone(prompts_module.prompt_optional_secret("Secret?"))
        with mock.patch(
            "ethernity.cli.shared.ui.prompts_core.questionary.password",
            return_value=_Ask(["value"]),
        ):
            self.assertEqual(prompts_module.prompt_optional_secret("Secret?"), "value")
        with mock.patch(
            "ethernity.cli.shared.ui.prompts_core.questionary.password",
            return_value=_Ask([None]),
        ):
            with self.assertRaises(KeyboardInterrupt):
                prompts_module.prompt_optional_secret("Secret?")
        self.assertGreaterEqual(print_prompt_header.call_count, 3)

    def test_prompt_required_secret_retries_and_accepts(self) -> None:
        context = _context()
        context.console_err.print = mock.MagicMock()
        with mock.patch(
            "ethernity.cli.shared.ui.prompts_core.questionary.password",
            return_value=_Ask(["", "secret"]),
        ):
            value = prompts_module.prompt_required_secret("Secret?", context=context)
        self.assertEqual(value, "secret")
        context.console_err.print.assert_called_once()

    def test_prompt_required_secret_keyboard_interrupt(self) -> None:
        with mock.patch(
            "ethernity.cli.shared.ui.prompts_core.questionary.password", return_value=_Ask([None])
        ):
            with self.assertRaises(KeyboardInterrupt):
                prompts_module.prompt_required_secret("Secret?")

    @mock.patch("ethernity.cli.shared.ui.prompts_core.prompt_choice_list", return_value="x")
    def test_prompt_choice_delegates_to_choice_list(
        self,
        prompt_choice_list: mock.MagicMock,
    ) -> None:
        value = prompts_module.prompt_choice("Pick", {"x": "X"}, default="x")
        self.assertEqual(value, "x")
        prompt_choice_list.assert_called_once()

    def test_prompt_yes_no(self) -> None:
        with mock.patch(
            "ethernity.cli.shared.ui.prompts_core.questionary.confirm", return_value=_Ask([True])
        ):
            self.assertTrue(prompts_module.prompt_yes_no("Continue?", default=True))
        with mock.patch(
            "ethernity.cli.shared.ui.prompts_core.questionary.confirm", return_value=_Ask([None])
        ):
            with self.assertRaises(KeyboardInterrupt):
                prompts_module.prompt_yes_no("Continue?", default=False)

    def test_prompt_optional_required_and_multiline(self) -> None:
        with mock.patch(
            "ethernity.cli.shared.ui.prompts_core.questionary.text", return_value=_Ask([" value "])
        ):
            self.assertEqual(prompts_module.prompt_optional("Name"), "value")
        with mock.patch(
            "ethernity.cli.shared.ui.prompts_core.questionary.text", return_value=_Ask(["  "])
        ):
            self.assertIsNone(prompts_module.prompt_optional("Name"))
        with mock.patch(
            "ethernity.cli.shared.ui.prompts_core.questionary.text", return_value=_Ask([None])
        ):
            with self.assertRaises(KeyboardInterrupt):
                prompts_module.prompt_optional("Name")

        context = _context()
        context.console_err.print = mock.MagicMock()
        with mock.patch(
            "ethernity.cli.shared.ui.prompts_core.questionary.text",
            return_value=_Ask(["", "ready"]),
        ):
            self.assertEqual(prompts_module.prompt_required("Value", context=context), "ready")
        context.console_err.print.assert_called()

        with mock.patch(
            "ethernity.cli.shared.ui.prompts_core.questionary.text",
            return_value=_Ask(["one\ntwo", "-"]),
        ):
            items = prompts_module.prompt_multiline("Lines", stop_on_dash=True)
        self.assertEqual(items, ["one", "two", "-"])

    def test_prompt_int_validation(self) -> None:
        context = _context()
        context.console_err.print = mock.MagicMock()
        with mock.patch(
            "ethernity.cli.shared.ui.prompts_core.questionary.text",
            return_value=_Ask(["", "abc", "0", "11", "5"]),
        ):
            value = prompts_module.prompt_int("Count", minimum=1, maximum=10, context=context)
        self.assertEqual(value, 5)
        self.assertGreaterEqual(context.console_err.print.call_count, 4)


class TestWorkspacePrompts(unittest.TestCase):
    @mock.patch("ethernity.cli.shared.ui.workspace.prompt_choice_list", return_value="source")
    def test_prompt_workspace_action_does_not_duplicate_first_blocker(
        self,
        prompt_choice_list: mock.MagicMock,
    ) -> None:
        sections = [
            workspace_module.WorkspaceSection(
                key="source",
                title="Source",
                status="missing",
                summary="Choose a source.",
                action_label="Choose source",
            ),
            workspace_module.WorkspaceSection(
                key="unlock",
                title="Unlock",
                status="ready",
                summary="Passphrase provided.",
                action_label="Edit unlock",
            ),
        ]

        result = workspace_module.prompt_workspace_action(
            "Workspace",
            sections,
            proceed_label="Review",
            context=_context(),
        )

        self.assertEqual(result, "source")
        choices = prompt_choice_list.call_args.args[0]
        values = [getattr(choice, "value", None) for choice in choices]
        self.assertEqual(values.count("source"), 1)
        self.assertIn("unlock", values)


class TestChoiceAndPickerInternals(unittest.TestCase):
    def test_prompt_choice_list_rejects_empty_choices(self) -> None:
        with self.assertRaisesRegex(ValueError, "list of choices needs to be provided"):
            prompts_module.prompt_choice_list([], default=None)

    @mock.patch(
        "ethernity.cli.shared.ui.prompts_core._select_with_initial_choice",
        return_value=_Ask([None]),
    )
    def test_prompt_choice_list_cancellation_raises_keyboard_interrupt(
        self,
        _select_with_initial_choice: mock.MagicMock,
    ) -> None:
        with self.assertRaises(KeyboardInterrupt):
            prompts_module.prompt_choice_list([("a", "A")], default="a")
        with self.assertRaises(KeyboardInterrupt):
            prompts_module.prompt_choice_list([("a", "A")], default=None)

    @mock.patch(
        "ethernity.cli.shared.ui.prompts_core._select_with_initial_choice",
        return_value=_Ask(["chosen"]),
    )
    def test_prompt_choice_list_uses_public_questionary_select(
        self,
        select_mock: mock.MagicMock,
    ) -> None:
        value = prompts_module.prompt_choice_list(
            [("a", "A"), ("b", "B")],
            default="b",
            title="Pick one",
            help_text="help",
            context=_context(),
        )
        self.assertEqual(value, "chosen")
        select_mock.assert_called_once()
        self.assertEqual(select_mock.call_args.kwargs["initial_choice"], "b")

    @mock.patch(
        "ethernity.cli.shared.ui.prompts_core._select_with_initial_choice",
        return_value=_Ask(["chosen"]),
    )
    def test_prompt_choice_list_hides_inline_question_text_in_screen_mode(
        self,
        select_mock: mock.MagicMock,
    ) -> None:
        context = _context()
        context.screen_mode = True
        prompts_module.prompt_choice_list(
            [("a", "A")],
            default="a",
            title="Pick one",
            context=context,
        )
        self.assertEqual(select_mock.call_args.args[0], "")

    def test_questionary_style_highlights_current_choice(self) -> None:
        self.assertIn(
            ("highlighted", "fg:ansicyan bold"),
            prompts_core_module.QUESTIONARY_STYLE.style_rules,
        )
        self.assertNotIn(("selected", "reverse"), prompts_core_module.QUESTIONARY_STYLE.style_rules)

    @mock.patch(
        "ethernity.cli.shared.ui.prompts_core._select_with_initial_choice",
        return_value=_Ask(["chosen"]),
    )
    def test_prompt_choice_list_passes_unknown_default_as_initial_choice(
        self,
        select_mock: mock.MagicMock,
    ) -> None:
        prompts_module.prompt_choice_list([("a", "A")], default="missing", context=_context())
        self.assertEqual(select_mock.call_args.kwargs["initial_choice"], "missing")

    @mock.patch(
        "ethernity.cli.shared.ui.prompts_core._select_with_initial_choice",
        side_effect=[_Ask(["chosen"]), _Ask(["chosen"])],
    )
    def test_prompt_choice_list_shows_navigation_hint_once_per_screen_mode(
        self,
        select_mock: mock.MagicMock,
    ) -> None:
        context = _context()
        context.screen_mode = True
        prompts_module.prompt_choice_list([("a", "A")], default="a", context=context)
        prompts_module.prompt_choice_list([("b", "B")], default="b", context=context)
        self.assertTrue(select_mock.call_args_list[0].kwargs["show_navigation_hint"])
        self.assertFalse(select_mock.call_args_list[1].kwargs["show_navigation_hint"])

    @mock.patch(
        "ethernity.cli.shared.ui.prompts_core._select_with_initial_choice",
        return_value=_Ask(["chosen"]),
    )
    def test_prompt_choice_list_preserves_separators(
        self,
        select_mock: mock.MagicMock,
    ) -> None:
        prompts_module.prompt_choice_list(
            [questionary.Separator("Start"), ("a", "A")],
            default="a",
            context=_context(),
        )
        choices = select_mock.call_args.kwargs["choices"]
        self.assertIsInstance(choices[0], questionary.Separator)
        self.assertEqual(choices[1].title, "A")

    @mock.patch(
        "ethernity.cli.shared.ui.prompts_core._select_with_initial_choice",
        return_value=_Ask(["chosen"]),
    )
    def test_prompt_choice_list_preserves_choice_objects(
        self,
        select_mock: mock.MagicMock,
    ) -> None:
        prompts_module.prompt_choice_list(
            [questionary.Choice("A", value="a", description="desc")],
            default="a",
            context=_context(),
        )
        choice = select_mock.call_args.kwargs["choices"][0]
        self.assertIsInstance(choice, questionary.Choice)
        self.assertEqual(choice.value, "a")
        self.assertEqual(choice.description, "desc")

    def test_iter_picker_entries_filters_and_keeps_navigation_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".hidden").write_text("x", encoding="utf-8")
            (root / "file.txt").write_text("x", encoding="utf-8")
            (root / "dir").mkdir()
            entries = picker_module._iter_picker_entries(
                picker_module._PickerState(
                    current_dir=root,
                    allow_files=True,
                    allow_dirs=True,
                    include_hidden=False,
                )
            )
            values = {entry.label for entry in entries}
            self.assertIn("file.txt", values)
            self.assertIn("dir/", values)
            self.assertNotIn(".hidden", values)

            dir_only = picker_module._iter_picker_entries(
                picker_module._PickerState(
                    current_dir=root,
                    allow_files=False,
                    allow_dirs=False,
                    include_hidden=False,
                )
            )
            self.assertEqual([entry.label for entry in dir_only], ["dir/"])
            self.assertFalse(dir_only[0].selectable)

            hidden = picker_module._iter_picker_entries(
                picker_module._PickerState(
                    current_dir=root,
                    allow_files=True,
                    allow_dirs=True,
                    include_hidden=True,
                    filter_text="hidden",
                )
            )
            self.assertEqual([entry.label for entry in hidden], [".hidden"])

            with self.assertRaisesRegex(ValueError, "dir not found"):
                picker_module._resolve_picker_directory(str(root / "missing"))

    def test_iter_picker_entries_empty_directory_returns_no_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = picker_module._iter_picker_entries(
                picker_module._PickerState(
                    current_dir=root,
                    allow_files=False,
                    allow_dirs=False,
                    include_hidden=False,
                )
            )
            self.assertEqual(entries, [])

    @mock.patch("ethernity.cli.shared.ui.picker.prompt_optional_path", side_effect=[".", ".", "."])
    @mock.patch(
        "ethernity.cli.shared.ui.picker.prompt_choice",
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

        value = picker_module._run_picker_flow(
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

        value2 = picker_module._run_picker_flow(
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

    @mock.patch("ethernity.cli.shared.ui.picker.prompt_optional_path", return_value=None)
    @mock.patch("ethernity.cli.shared.ui.picker.prompt_choice", return_value="select")
    def test_run_picker_flow_uses_last_picker_dir_default(
        self,
        _prompt_choice: mock.MagicMock,
        _prompt_optional_path: mock.MagicMock,
    ) -> None:
        context = _context()
        context.last_picker_dir = "/tmp/last-picker"
        select_func = mock.MagicMock(return_value="/tmp/last-picker/chosen.txt")
        value = picker_module._run_picker_flow(
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

    @mock.patch("ethernity.cli.shared.ui.picker.prompt_optional_path", return_value=".")
    @mock.patch("ethernity.cli.shared.ui.picker.prompt_choice", return_value="select")
    def test_run_picker_flow_updates_last_picker_dir_after_select(
        self,
        _prompt_choice: mock.MagicMock,
        _prompt_optional_path: mock.MagicMock,
    ) -> None:
        context = _context()
        context.last_picker_dir = "."
        select_func = mock.MagicMock(return_value="/tmp/out/file.txt")
        picker_module._run_picker_flow(
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
        self.assertEqual(Path(context.last_picker_dir), Path("/tmp/out"))

    @mock.patch("ethernity.cli.shared.ui.picker.prompt_choice", return_value="manual")
    def test_run_picker_flow_updates_last_picker_dir_after_manual(
        self,
        _prompt_choice: mock.MagicMock,
    ) -> None:
        context = _context()
        manual_func = mock.MagicMock(return_value="/tmp/manual/path.txt")
        picker_module._run_picker_flow(
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
        self.assertEqual(Path(context.last_picker_dir), Path("/tmp/manual"))

    @mock.patch("ethernity.cli.shared.ui.picker.prompt_choice_list")
    def test_prompt_select_entries_single(
        self,
        prompt_choice_list: mock.MagicMock,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.txt"
            path.write_text("x", encoding="utf-8")
            prompt_choice_list.return_value = ("select", str(path))
            value = picker_module._prompt_select_entries(
                "Pick one",
                directory=tmp,
                allow_files=True,
                allow_dirs=False,
                include_hidden=False,
                help_text="help",
                multi=False,
                context=_context(),
            )
        self.assertEqual(value, str(path))
        prompt_choice_list.assert_called_once()

    @mock.patch("ethernity.cli.shared.ui.picker.prompt_choice_list")
    def test_prompt_select_entries_multi_retries_on_empty(
        self,
        prompt_choice_list: mock.MagicMock,
    ) -> None:
        context = _context()
        context.console.print = mock.MagicMock()
        context.console_err.print = mock.MagicMock()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.txt"
            path.write_text("x", encoding="utf-8")
            prompt_choice_list.side_effect = [
                ("done", ""),
                ("toggle", str(path)),
                ("done", ""),
            ]
            values = picker_module._prompt_select_entries(
                "Pick many",
                directory=tmp,
                allow_files=True,
                allow_dirs=False,
                include_hidden=False,
                help_text="help",
                multi=True,
                context=context,
            )
        self.assertEqual(values, [str(path)])
        context.console_err.print.assert_called()

    @mock.patch("ethernity.cli.shared.ui.picker.prompt_choice_list")
    def test_prompt_select_entries_multi_hides_inline_question_text_in_screen_mode(
        self,
        prompt_choice_list: mock.MagicMock,
    ) -> None:
        context = _context()
        context.screen_mode = True
        context.console.print = mock.MagicMock()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.txt"
            path.write_text("x", encoding="utf-8")
            prompt_choice_list.side_effect = [("toggle", str(path)), ("done", "")]
            values = picker_module._prompt_select_entries(
                "Pick many",
                directory=tmp,
                allow_files=True,
                allow_dirs=False,
                include_hidden=False,
                help_text="help",
                multi=True,
                context=context,
            )
        self.assertEqual(values, [str(path)])
        self.assertIn("Pick many - ", prompt_choice_list.call_args_list[0].kwargs["title"])

    @mock.patch("ethernity.cli.shared.ui.picker._prompt_select_entries", return_value=["a", "b"])
    def test_prompt_select_paths_wrapper(self, _prompt_select_entries: mock.MagicMock) -> None:
        values = prompts_module.prompt_select_paths("Pick", directory=".")
        self.assertEqual(values, ["a", "b"])

    @mock.patch("ethernity.cli.shared.ui.picker._prompt_select_entries", return_value="a")
    def test_prompt_select_path_wrapper(self, _prompt_select_entries: mock.MagicMock) -> None:
        value = prompts_module.prompt_select_path("Pick", directory=".")
        self.assertEqual(value, "a")

    @mock.patch("ethernity.cli.shared.ui.picker._run_picker_flow", return_value="picked")
    def test_prompt_path_with_picker_delegates(self, run_picker_flow: mock.MagicMock) -> None:
        value = prompts_module.prompt_path_with_picker("Path", kind="file")
        self.assertEqual(value, "picked")
        run_picker_flow.assert_called_once()

    @mock.patch("ethernity.cli.shared.ui.picker._run_picker_flow", return_value=None)
    def test_prompt_optional_path_with_picker_delegates(
        self,
        run_picker_flow: mock.MagicMock,
    ) -> None:
        value = prompts_module.prompt_optional_path_with_picker("Path", kind="file")
        self.assertIsNone(value)
        run_picker_flow.assert_called_once()

    @mock.patch("ethernity.cli.shared.ui.picker._run_picker_flow", return_value=None)
    def test_prompt_optional_path_with_picker_allow_new_defaults_to_manual(
        self,
        run_picker_flow: mock.MagicMock,
    ) -> None:
        prompts_module.prompt_optional_path_with_picker("Path", kind="dir", allow_new=True)
        run_picker_flow.assert_called_once()
        self.assertEqual(
            run_picker_flow.call_args.kwargs["selection_prompt"],
            "Enter path / Pick existing path",
        )
        self.assertEqual(run_picker_flow.call_args.kwargs["select_label"], "Pick existing path")
        self.assertEqual(run_picker_flow.call_args.kwargs["default_mode"], "manual")


class TestPathValidationFlows(unittest.TestCase):
    def test_validate_path_cases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file_path = root / "a.txt"
            file_path.write_text("x", encoding="utf-8")
            dir_path = root / "d"
            dir_path.mkdir()

            self.assertIsNone(picker_module.validate_path(str(file_path), kind="file"))
            self.assertIsNone(picker_module.validate_path(str(dir_path), kind="dir"))
            self.assertIn(
                "not a directory", picker_module.validate_path(str(file_path), kind="dir") or ""
            )
            self.assertIn(
                "not a file", picker_module.validate_path(str(dir_path), kind="file") or ""
            )
            self.assertIn(
                "not found",
                picker_module.validate_path(str(root / "missing"), kind="path") or "",
            )
            self.assertIsNone(
                picker_module.validate_path(str(root / "new"), kind="path", allow_new=True)
            )

    @mock.patch(
        "ethernity.cli.shared.ui.picker.validate_path", side_effect=["bad", None, None, None]
    )
    @mock.patch("ethernity.cli.shared.ui.picker.prompt_optional", side_effect=[None, "value"])
    @mock.patch("ethernity.cli.shared.ui.picker.prompt_required", side_effect=["-", "bad", "good"])
    def test_prompt_path_required_optional_and_stdin(
        self,
        _prompt_required: mock.MagicMock,
        _prompt_optional: mock.MagicMock,
        _validate_path: mock.MagicMock,
    ) -> None:
        context = _context()
        context.console_err.print = mock.MagicMock()
        self.assertEqual(
            picker_module._prompt_path(
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
            picker_module._prompt_path(
                "Path",
                kind="file",
                required=True,
                help_text=None,
                context=context,
            ),
            "good",
        )
        self.assertIsNone(
            picker_module._prompt_path(
                "Path",
                kind="file",
                required=False,
                help_text=None,
                context=context,
            )
        )
        self.assertEqual(
            picker_module._prompt_path(
                "Path",
                kind="file",
                required=False,
                help_text=None,
                context=context,
            ),
            "value",
        )

    @mock.patch("ethernity.cli.shared.ui.picker._prompt_path", return_value="x")
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
            "ethernity.cli.shared.ui.picker.prompt_multiline",
            side_effect=[[], ["-"], ["a.txt", "-"], ["bad"], ["ok"]],
        ):
            with mock.patch(
                "ethernity.cli.shared.ui.picker.validate_path",
                side_effect=["broken", None],
            ):
                values = picker_module.prompt_required_paths(
                    "Paths",
                    kind="file",
                    allow_stdin=False,
                    context=context,
                )
        self.assertEqual(values, ["ok"])
        self.assertGreaterEqual(context.console_err.print.call_count, 3)

        with mock.patch("ethernity.cli.shared.ui.picker.prompt_multiline", return_value=["-"]):
            values = picker_module.prompt_required_paths(
                "Paths",
                kind="file",
                allow_stdin=True,
                context=_context(),
            )
        self.assertEqual(values, ["-"])

    @mock.patch("ethernity.cli.shared.ui.picker._run_picker_flow", return_value=["a.txt"])
    def test_prompt_paths_with_picker_delegates(self, run_picker_flow: mock.MagicMock) -> None:
        values = prompts_module.prompt_paths_with_picker("Enter paths")
        self.assertEqual(values, ["a.txt"])
        run_picker_flow.assert_called_once()


if __name__ == "__main__":
    unittest.main()
