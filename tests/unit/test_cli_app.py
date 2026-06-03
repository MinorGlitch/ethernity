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

import contextlib
import importlib
import unittest
from dataclasses import dataclass
from unittest import mock

import typer

from ethernity.cli.features.config.onboarding import FirstRunOnboardingResult
from ethernity.cli.shared.types import CliContextState, CompactArgs, ExtendArgs, RecoverArgs
from ethernity.config import BackupDefaults, CliDefaults, DebugDefaults, ExtendDefaults, UiDefaults

app_module = importlib.import_module("ethernity.cli.bootstrap.app")


@dataclass
class _Ctx:
    invoked_subcommand: str | None = None
    obj: CliContextState | None = None


class TestCliApp(unittest.TestCase):
    @mock.patch(
        "ethernity.cli.bootstrap.app.prompt_passphrase_unlock_material",
        return_value=("secret", [], [], [], []),
    )
    @mock.patch("ethernity.cli.bootstrap.app.prompt_int", side_effect=[3, 2])
    @mock.patch(
        "ethernity.cli.bootstrap.app.prompt_choice",
        side_effect=["folder", "extension-shards", "not-stored"],
    )
    @mock.patch("ethernity.cli.bootstrap.app.prompt_paths_with_picker", return_value=["/tmp/input"])
    @mock.patch("ethernity.cli.bootstrap.app.prompt_path_with_picker", return_value="/tmp/root")
    def test_prompt_home_extend_args_prompts_folder_then_passphrase_then_files(
        self,
        prompt_path_with_picker: mock.MagicMock,
        prompt_paths_with_picker: mock.MagicMock,
        _prompt_choice: mock.MagicMock,
        _prompt_int: mock.MagicMock,
        prompt_passphrase_unlock_material: mock.MagicMock,
    ) -> None:
        calls: list[str] = []

        def _record_root(*args, **kwargs):
            calls.append("root")
            return "/tmp/root"

        def _record_unlock(*args, **kwargs):
            calls.append("passphrase")
            return ("secret", [], [], [], [])

        def _record_paths(*args, **kwargs):
            calls.append("paths")
            return ["/tmp/input"]

        prompt_path_with_picker.side_effect = _record_root
        prompt_paths_with_picker.side_effect = _record_paths
        prompt_passphrase_unlock_material.side_effect = _record_unlock

        args = app_module._prompt_home_extend_args(
            config="cfg",
            paper="A4",
            design="forge",
            quiet=False,
        )

        self.assertEqual(calls, ["root", "passphrase", "paths"])
        self.assertEqual(args.root_dir, "/tmp/root")
        self.assertIsNone(args.scan)
        self.assertEqual(args.input, ["/tmp/input"])
        self.assertIsNone(args.input_dir)
        self.assertEqual(args.passphrase, "secret")
        self.assertEqual(args.unlock_policy, "self-contained")
        self.assertEqual(args.shard_count, 3)
        self.assertEqual(args.shard_threshold, 2)
        self.assertEqual(args.signing_key_mode, "not-stored")
        self.assertEqual(_prompt_int.call_args_list[0].kwargs["maximum"], 255)
        self.assertEqual(_prompt_int.call_args_list[1].kwargs["maximum"], 3)

    @mock.patch(
        "ethernity.cli.bootstrap.app.prompt_passphrase_unlock_material",
        return_value=(None, ["shards.txt"], ["payloads.txt"], ["scan.pdf"], [object()]),
    )
    @mock.patch(
        "ethernity.cli.bootstrap.app.prompt_choice",
        side_effect=["folder", "reuse-root", "not-stored"],
    )
    @mock.patch("ethernity.cli.bootstrap.app.prompt_paths_with_picker", return_value=["/tmp/input"])
    @mock.patch("ethernity.cli.bootstrap.app.prompt_path_with_picker", return_value="/tmp/root")
    def test_prompt_home_extend_args_preserves_shard_unlock_inputs(
        self,
        _prompt_path_with_picker: mock.MagicMock,
        _prompt_paths_with_picker: mock.MagicMock,
        _prompt_choice: mock.MagicMock,
        _prompt_passphrase_unlock_material: mock.MagicMock,
    ) -> None:
        args = app_module._prompt_home_extend_args(
            config="cfg",
            paper="A4",
            design="forge",
            quiet=False,
        )

        self.assertIsNone(args.passphrase)
        self.assertEqual(args.shard_fallback_file, ["shards.txt"])
        self.assertEqual(args.shard_payloads_file, ["payloads.txt"])
        self.assertEqual(args.shard_scan, ["scan.pdf"])
        self.assertEqual(len(args.shard_frames or []), 1)
        self.assertEqual(args.unlock_policy, "reuse-root")
        self.assertEqual(args.signing_key_mode, "not-stored")

    @mock.patch(
        "ethernity.cli.bootstrap.app.prompt_passphrase_unlock_material",
        return_value=(None, ["shards.txt"], ["payloads.txt"], ["scan.pdf"], [object()]),
    )
    @mock.patch("ethernity.cli.bootstrap.app.prompt_int", side_effect=[4, 2])
    @mock.patch(
        "ethernity.cli.bootstrap.app.prompt_choice",
        side_effect=["folder", "reuse-root", "sharded"],
    )
    @mock.patch("ethernity.cli.bootstrap.app.prompt_paths_with_picker", return_value=["/tmp/input"])
    @mock.patch("ethernity.cli.bootstrap.app.prompt_path_with_picker", return_value="/tmp/root")
    def test_prompt_home_extend_args_allows_reuse_root_with_signing_key_shards(
        self,
        _prompt_path_with_picker: mock.MagicMock,
        _prompt_paths_with_picker: mock.MagicMock,
        _prompt_choice: mock.MagicMock,
        _prompt_int: mock.MagicMock,
        _prompt_passphrase_unlock_material: mock.MagicMock,
    ) -> None:
        args = app_module._prompt_home_extend_args(
            config="cfg",
            paper="A4",
            design="forge",
            quiet=False,
        )

        self.assertEqual(args.unlock_policy, "reuse-root")
        self.assertIsNone(args.shard_count)
        self.assertIsNone(args.shard_threshold)
        self.assertEqual(args.signing_key_mode, "sharded")
        self.assertEqual(args.signing_key_shard_count, 4)
        self.assertEqual(args.signing_key_shard_threshold, 2)

    @mock.patch(
        "ethernity.cli.bootstrap.app.prompt_passphrase_unlock_material",
        return_value=("secret", [], [], [], []),
    )
    @mock.patch("ethernity.cli.bootstrap.app.prompt_choice", side_effect=["folder", "plaintext"])
    @mock.patch("ethernity.cli.bootstrap.app.prompt_paths_with_picker", return_value=["/tmp/input"])
    @mock.patch("ethernity.cli.bootstrap.app.prompt_path_with_picker", return_value="/tmp/root")
    def test_prompt_home_extend_args_allows_explicit_plaintext_output(
        self,
        _prompt_path_with_picker: mock.MagicMock,
        _prompt_paths_with_picker: mock.MagicMock,
        _prompt_choice: mock.MagicMock,
        _prompt_passphrase_unlock_material: mock.MagicMock,
    ) -> None:
        args = app_module._prompt_home_extend_args(
            config="cfg",
            paper="A4",
            design="forge",
            quiet=False,
        )

        self.assertEqual(args.unlock_policy, "self-contained")
        self.assertEqual(args.shard_count, 0)
        self.assertEqual(args.signing_key_mode, "not-stored")

    @mock.patch(
        "ethernity.cli.bootstrap.app.prompt_passphrase_unlock_material",
        return_value=("secret", [], [], [], []),
    )
    @mock.patch(
        "ethernity.cli.bootstrap.app.prompt_int",
        side_effect=[5, 3, 4, 2],
    )
    @mock.patch(
        "ethernity.cli.bootstrap.app.prompt_choice",
        side_effect=["folder", "extension-shards", "sharded"],
    )
    @mock.patch("ethernity.cli.bootstrap.app.prompt_paths_with_picker", return_value=["/tmp/input"])
    @mock.patch("ethernity.cli.bootstrap.app.prompt_path_with_picker", return_value="/tmp/root")
    def test_prompt_home_extend_args_allows_signing_key_shards(
        self,
        _prompt_path_with_picker: mock.MagicMock,
        _prompt_paths_with_picker: mock.MagicMock,
        _prompt_choice: mock.MagicMock,
        _prompt_int: mock.MagicMock,
        _prompt_passphrase_unlock_material: mock.MagicMock,
    ) -> None:
        args = app_module._prompt_home_extend_args(
            config="cfg",
            paper="A4",
            design="forge",
            quiet=False,
        )

        self.assertEqual(args.shard_count, 5)
        self.assertEqual(args.shard_threshold, 3)
        self.assertEqual(args.signing_key_mode, "sharded")
        self.assertEqual(args.signing_key_shard_count, 4)
        self.assertEqual(args.signing_key_shard_threshold, 2)
        self.assertEqual(_prompt_int.call_args_list[0].kwargs["maximum"], 255)
        self.assertEqual(_prompt_int.call_args_list[2].kwargs["maximum"], 255)

    @mock.patch(
        "ethernity.cli.bootstrap.app.prompt_passphrase_unlock_material",
        return_value=("secret", [], [], [], []),
    )
    @mock.patch("ethernity.cli.bootstrap.app._prompt_home_extend_stale_head_ack", return_value=True)
    @mock.patch("ethernity.cli.bootstrap.app.prompt_optional", return_value=None)
    @mock.patch("ethernity.cli.bootstrap.app.prompt_choice", side_effect=["scan", "plaintext"])
    @mock.patch(
        "ethernity.cli.bootstrap.app.prompt_paths_with_picker",
        side_effect=[["/tmp/root.pdf", "/tmp/ext1.pdf"], ["/tmp/input"]],
    )
    @mock.patch(
        "ethernity.cli.bootstrap.app.prompt_optional_path_with_picker",
        return_value="/tmp/output",
    )
    @mock.patch("ethernity.cli.bootstrap.app.prompt_path_with_picker")
    def test_prompt_home_extend_args_defaults_to_scanned_chain_source(
        self,
        prompt_path_with_picker: mock.MagicMock,
        prompt_optional_path_with_picker: mock.MagicMock,
        prompt_paths_with_picker: mock.MagicMock,
        _prompt_choice: mock.MagicMock,
        prompt_optional: mock.MagicMock,
        prompt_stale_head_ack: mock.MagicMock,
        _prompt_passphrase_unlock_material: mock.MagicMock,
    ) -> None:
        args = app_module._prompt_home_extend_args(
            config="cfg",
            paper="A4",
            design="forge",
            quiet=False,
        )

        self.assertEqual(args.root_dir, "/tmp/output")
        self.assertEqual(args.scan, ["/tmp/root.pdf", "/tmp/ext1.pdf"])
        self.assertEqual(args.input, ["/tmp/input"])
        self.assertEqual(args.unlock_policy, "self-contained")
        self.assertEqual(args.shard_count, 0)
        self.assertTrue(args.allow_stale_head)
        prompt_path_with_picker.assert_not_called()
        prompt_optional_path_with_picker.assert_called_once()
        prompt_optional.assert_called_once()
        prompt_stale_head_ack.assert_called_once()
        self.assertEqual(prompt_paths_with_picker.call_count, 2)

    @mock.patch(
        "ethernity.cli.bootstrap.app.prompt_passphrase_unlock_material",
        return_value=("secret", [], [], [], []),
    )
    @mock.patch("ethernity.cli.bootstrap.app.prompt_optional", return_value="AB" * 32)
    @mock.patch("ethernity.cli.bootstrap.app.prompt_choice", side_effect=["scan", "plaintext"])
    @mock.patch(
        "ethernity.cli.bootstrap.app.prompt_paths_with_picker",
        side_effect=[["/tmp/root.pdf", "/tmp/ext1.pdf"], ["/tmp/input"]],
    )
    @mock.patch(
        "ethernity.cli.bootstrap.app.prompt_optional_path_with_picker",
        return_value="/tmp/output",
    )
    @mock.patch("ethernity.cli.bootstrap.app.prompt_path_with_picker")
    def test_prompt_home_extend_args_preserves_scan_expected_head(
        self,
        _prompt_path_with_picker: mock.MagicMock,
        _prompt_optional_path_with_picker: mock.MagicMock,
        _prompt_paths_with_picker: mock.MagicMock,
        _prompt_choice: mock.MagicMock,
        _prompt_optional: mock.MagicMock,
        _prompt_passphrase_unlock_material: mock.MagicMock,
    ) -> None:
        args = app_module._prompt_home_extend_args(
            config="cfg",
            paper="A4",
            design="forge",
            quiet=False,
        )

        self.assertEqual(args.expected_head_doc_hash, "ab" * 32)

    @mock.patch("ethernity.cli.bootstrap.app._prompt_home_auth_inputs")
    @mock.patch(
        "ethernity.cli.bootstrap.app.prompt_passphrase_unlock_material",
        return_value=(None, ["shards.txt"], ["payloads.txt"], ["scan.pdf"], [object()]),
    )
    @mock.patch(
        "ethernity.cli.bootstrap.app.prompt_optional_path_with_picker",
        return_value="/tmp/output",
    )
    @mock.patch("ethernity.cli.bootstrap.app.prompt_choice", return_value="folder")
    @mock.patch("ethernity.cli.bootstrap.app.prompt_path_with_picker", return_value="/tmp/root")
    def test_prompt_home_compact_args_preserves_shard_inputs_without_extra_auth_prompt(
        self,
        _prompt_path_with_picker: mock.MagicMock,
        _prompt_choice: mock.MagicMock,
        _prompt_optional_path_with_picker: mock.MagicMock,
        _prompt_passphrase_unlock_material: mock.MagicMock,
        prompt_home_auth_inputs: mock.MagicMock,
    ) -> None:
        args = app_module._prompt_home_compact_args(
            config="cfg",
            paper="A4",
            design="forge",
            quiet=False,
        )

        self.assertIsNone(args.passphrase)
        self.assertEqual(args.shard_fallback_file, ["shards.txt"])
        self.assertEqual(args.shard_payloads_file, ["payloads.txt"])
        self.assertEqual(args.shard_scan, ["scan.pdf"])
        self.assertEqual(len(args.shard_frames or []), 1)
        prompt_home_auth_inputs.assert_not_called()
        self.assertIsNone(args.auth_fallback_file)
        self.assertIsNone(args.auth_payloads_file)

    @mock.patch("ethernity.cli.bootstrap.app._prompt_home_auth_inputs")
    @mock.patch(
        "ethernity.cli.bootstrap.app.prompt_passphrase_unlock_material",
        return_value=("secret", [], [], [], []),
    )
    @mock.patch(
        "ethernity.cli.bootstrap.app.prompt_optional_path_with_picker",
        return_value="/tmp/output",
    )
    @mock.patch(
        "ethernity.cli.bootstrap.app.prompt_paths_with_picker",
        return_value=["/tmp/root.pdf", "/tmp/ext1.pdf"],
    )
    @mock.patch("ethernity.cli.bootstrap.app.prompt_choice", return_value="scan")
    @mock.patch("ethernity.cli.bootstrap.app.prompt_path_with_picker")
    def test_prompt_home_compact_args_defaults_to_scanned_source(
        self,
        prompt_path_with_picker: mock.MagicMock,
        _prompt_choice: mock.MagicMock,
        _prompt_paths_with_picker: mock.MagicMock,
        _prompt_optional_path_with_picker: mock.MagicMock,
        _prompt_passphrase_unlock_material: mock.MagicMock,
        prompt_home_auth_inputs: mock.MagicMock,
    ) -> None:
        args = app_module._prompt_home_compact_args(
            config="cfg",
            paper="A4",
            design="forge",
            quiet=False,
        )

        self.assertIsNone(args.root_dir)
        self.assertEqual(args.scan, ["/tmp/root.pdf", "/tmp/ext1.pdf"])
        self.assertEqual(args.output_dir, "/tmp/output")
        self.assertEqual(args.passphrase, "secret")
        prompt_path_with_picker.assert_not_called()
        prompt_home_auth_inputs.assert_not_called()

    def test_argv_invokes_api_detects_top_level_api_surface(self) -> None:
        self.assertTrue(app_module._argv_invokes_api(["ethernity", "api"]))
        self.assertTrue(app_module._argv_invokes_api(["ethernity", "--config", "cfg.toml", "api"]))
        self.assertFalse(app_module._argv_invokes_api(["ethernity", "backup"]))

    def test_should_run_first_run_onboarding_only_for_interactive_root(self) -> None:
        with (
            mock.patch("ethernity.cli.bootstrap.app.sys.stdin.isatty", return_value=True),
            mock.patch("ethernity.cli.bootstrap.app.sys.stdout.isatty", return_value=True),
        ):
            self.assertTrue(app_module._should_run_first_run_onboarding(None))
            self.assertFalse(app_module._should_run_first_run_onboarding("backup"))
        with (
            mock.patch("ethernity.cli.bootstrap.app.sys.stdin.isatty", return_value=False),
            mock.patch("ethernity.cli.bootstrap.app.sys.stdout.isatty", return_value=True),
        ):
            self.assertFalse(app_module._should_run_first_run_onboarding(None))

    def test_subcommand_config_override_extracts_supported_forms(self) -> None:
        self.assertEqual(
            app_module._subcommand_config_override(
                ["ethernity", "backup", "--config", "custom.toml"]
            ),
            "custom.toml",
        )
        self.assertEqual(
            app_module._subcommand_config_override(["ethernity", "backup", "--config=custom.toml"]),
            "custom.toml",
        )
        self.assertIsNone(
            app_module._subcommand_config_override(
                ["ethernity", "backup", "--", "--config", "ignored.toml"]
            )
        )

    @mock.patch("ethernity.cli.bootstrap.app.configure_ui")
    @mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False)
    @mock.patch("ethernity.cli.bootstrap.app.load_cli_defaults", return_value=CliDefaults())
    def test_cli_load_defaults_uses_subcommand_config_override(
        self,
        load_cli_defaults: mock.MagicMock,
        _run_startup: mock.MagicMock,
        _configure_ui: mock.MagicMock,
    ) -> None:
        ctx = _Ctx(invoked_subcommand="backup")
        with mock.patch.object(
            app_module.sys,
            "argv",
            ["ethernity", "backup", "--config", "custom.toml"],
        ):
            app_module.cli(
                ctx,
                config=None,
                paper=None,
                design=None,
                debug=False,
                debug_max_bytes=1024,
                debug_reveal_secrets=False,
                quiet=False,
                no_color=False,
                no_animations=False,
                init_config=False,
                version=False,
            )
        load_cli_defaults.assert_called_once_with(path="custom.toml")

    @mock.patch("ethernity.cli.bootstrap.app.configure_ui")
    @mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False)
    @mock.patch("ethernity.cli.bootstrap.app.load_cli_defaults", return_value=CliDefaults())
    def test_cli_load_defaults_prefers_global_config_value(
        self,
        load_cli_defaults: mock.MagicMock,
        _run_startup: mock.MagicMock,
        _configure_ui: mock.MagicMock,
    ) -> None:
        ctx = _Ctx(invoked_subcommand="backup")
        with mock.patch.object(
            app_module.sys,
            "argv",
            ["ethernity", "backup", "--config", "subcommand.toml"],
        ):
            app_module.cli(
                ctx,
                config="global.toml",
                paper=None,
                design=None,
                debug=False,
                debug_max_bytes=1024,
                debug_reveal_secrets=False,
                quiet=False,
                no_color=False,
                no_animations=False,
                init_config=False,
                version=False,
            )
        load_cli_defaults.assert_called_once_with(path="global.toml")

    @mock.patch("ethernity.cli.bootstrap.app.configure_ui")
    @mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False)
    @mock.patch("ethernity.cli.bootstrap.app.load_cli_defaults", return_value=CliDefaults())
    def test_cli_api_subcommand_bootstraps_defaults_from_config_override(
        self,
        load_cli_defaults: mock.MagicMock,
        run_startup: mock.MagicMock,
        _configure_ui: mock.MagicMock,
    ) -> None:
        ctx = _Ctx(invoked_subcommand="api")
        with mock.patch.object(
            app_module.sys,
            "argv",
            ["ethernity", "api", "recover", "--config", "custom.toml"],
        ):
            app_module.cli(
                ctx,
                config=None,
                paper=None,
                design=None,
                debug=False,
                debug_max_bytes=1024,
                debug_reveal_secrets=False,
                quiet=False,
                no_color=False,
                no_animations=False,
                init_config=False,
                version=False,
            )
        load_cli_defaults.assert_called_once_with(path="custom.toml")
        run_startup.assert_not_called()
        state = ctx.obj
        if state is None:
            self.fail("expected CLI context state")
        self.assertEqual(state.config, "custom.toml")
        self.assertTrue(state.config_explicit)

    @mock.patch("ethernity.cli.bootstrap.app.configure_ui")
    @mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False)
    @mock.patch("ethernity.cli.bootstrap.app.load_cli_defaults", return_value=CliDefaults())
    @mock.patch(
        "ethernity.cli.bootstrap.app.resolve_api_defaults_config_path",
        return_value=app_module.DEFAULT_CONFIG_PATH,
    )
    def test_cli_api_subcommand_uses_package_default_config_without_explicit_override(
        self,
        _resolve_api_defaults_config_path: mock.MagicMock,
        load_cli_defaults: mock.MagicMock,
        run_startup: mock.MagicMock,
        _configure_ui: mock.MagicMock,
    ) -> None:
        ctx = _Ctx(invoked_subcommand="api")
        with mock.patch.object(app_module.sys, "argv", ["ethernity", "api", "backup", "--help"]):
            app_module.cli(
                ctx,
                config=None,
                paper=None,
                design=None,
                debug=False,
                debug_max_bytes=1024,
                debug_reveal_secrets=False,
                quiet=False,
                no_color=False,
                no_animations=False,
                init_config=False,
                version=False,
            )
        load_cli_defaults.assert_not_called()
        run_startup.assert_not_called()
        state = ctx.obj
        if state is None:
            self.fail("expected CLI context state")
        self.assertEqual(state.config, str(app_module.DEFAULT_CONFIG_PATH))
        self.assertFalse(state.config_explicit)

    @mock.patch("ethernity.cli.bootstrap.app.configure_ui")
    @mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False)
    @mock.patch("ethernity.cli.bootstrap.app.load_cli_defaults", return_value=CliDefaults())
    def test_cli_api_config_get_skips_defaults_bootstrap(
        self,
        load_cli_defaults: mock.MagicMock,
        run_startup: mock.MagicMock,
        _configure_ui: mock.MagicMock,
    ) -> None:
        ctx = _Ctx(invoked_subcommand="api")
        with mock.patch.object(app_module.sys, "argv", ["ethernity", "api", "config", "get"]):
            app_module.cli(
                ctx,
                config=None,
                paper=None,
                design=None,
                debug=False,
                debug_max_bytes=1024,
                debug_reveal_secrets=False,
                quiet=False,
                no_color=False,
                no_animations=False,
                init_config=False,
                version=False,
            )
        load_cli_defaults.assert_not_called()
        run_startup.assert_not_called()
        state = ctx.obj
        if state is None:
            self.fail("expected CLI context state")
        self.assertIsNone(state.config)

    @mock.patch("ethernity.cli.bootstrap.app.configure_ui")
    @mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False)
    @mock.patch("ethernity.cli.bootstrap.app.load_cli_defaults", return_value=CliDefaults())
    def test_cli_config_subcommand_does_not_bootstrap_defaults_from_argv_config(
        self,
        load_cli_defaults: mock.MagicMock,
        _run_startup: mock.MagicMock,
        _configure_ui: mock.MagicMock,
    ) -> None:
        ctx = _Ctx(invoked_subcommand="config")
        with mock.patch.object(
            app_module.sys,
            "argv",
            ["ethernity", "config", "--config", "broken.toml", "--print-path"],
        ):
            app_module.cli(
                ctx,
                config=None,
                paper=None,
                design=None,
                debug=False,
                debug_max_bytes=1024,
                debug_reveal_secrets=False,
                quiet=False,
                no_color=False,
                no_animations=False,
                init_config=False,
                version=False,
            )
        load_cli_defaults.assert_called_once_with(path=None)

    @mock.patch("ethernity.cli.bootstrap.app.console.print")
    def test_version_callback(self, print_mock: mock.MagicMock) -> None:
        with self.assertRaises(typer.Exit):
            app_module._version_callback(True)
        print_mock.assert_called_once()
        app_module._version_callback(False)

    @mock.patch("ethernity.cli.bootstrap.app.console_err.print")
    @mock.patch("ethernity.cli.bootstrap.app.run_startup", side_effect=ValueError("startup-failed"))
    def test_cli_startup_exception_returns_exit_2(
        self,
        _run_startup: mock.MagicMock,
        print_err: mock.MagicMock,
    ) -> None:
        ctx = _Ctx()
        with self.assertRaises(typer.Exit) as exc_info:
            app_module.cli(
                ctx,
                config=None,
                paper=None,
                design=None,
                debug=False,
                debug_max_bytes=1024,
                debug_reveal_secrets=False,
                quiet=False,
                no_color=False,
                no_animations=False,
                init_config=False,
                version=False,
            )
        self.assertEqual(exc_info.exception.exit_code, 2)
        print_err.assert_called_once()

    @mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=True)
    def test_cli_startup_should_exit(
        self,
        _run_startup: mock.MagicMock,
    ) -> None:
        ctx = _Ctx()
        with self.assertRaises(typer.Exit) as exc_info:
            app_module.cli(
                ctx,
                config=None,
                paper=None,
                design=None,
                debug=False,
                debug_max_bytes=1024,
                debug_reveal_secrets=False,
                quiet=False,
                no_color=False,
                no_animations=False,
                init_config=False,
                version=False,
            )
        self.assertEqual(exc_info.exception.exit_code, 0)

    @mock.patch("ethernity.cli.bootstrap.app.console_err.print")
    @mock.patch("ethernity.cli.bootstrap.app.load_cli_defaults", return_value=CliDefaults())
    @mock.patch("ethernity.cli.bootstrap.app.sys.stdin.isatty", return_value=False)
    @mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False)
    def test_cli_no_subcommand_non_tty_errors(
        self,
        _run_startup: mock.MagicMock,
        _stdin_tty: mock.MagicMock,
        _load_cli_defaults: mock.MagicMock,
        print_err: mock.MagicMock,
    ) -> None:
        ctx = _Ctx(invoked_subcommand=None)
        with self.assertRaises(typer.Exit) as exc_info:
            app_module.cli(
                ctx,
                config=None,
                paper=None,
                design=None,
                debug=False,
                debug_max_bytes=1024,
                debug_reveal_secrets=False,
                quiet=False,
                no_color=False,
                no_animations=False,
                init_config=False,
                version=False,
            )
        self.assertEqual(exc_info.exception.exit_code, 2)
        print_err.assert_called_once()

    @mock.patch("ethernity.cli.bootstrap.app.prompt_home_action")
    @mock.patch("ethernity.cli.bootstrap.app.console_err.print")
    @mock.patch("ethernity.cli.bootstrap.app.load_cli_defaults", return_value=CliDefaults())
    @mock.patch("ethernity.cli.bootstrap.app.sys.stdout.isatty", return_value=False)
    @mock.patch("ethernity.cli.bootstrap.app.sys.stdin.isatty", return_value=True)
    @mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False)
    def test_cli_no_subcommand_non_tty_stdout_errors(
        self,
        _run_startup: mock.MagicMock,
        _stdin_tty: mock.MagicMock,
        _stdout_tty: mock.MagicMock,
        _load_cli_defaults: mock.MagicMock,
        print_err: mock.MagicMock,
        prompt_home_action: mock.MagicMock,
    ) -> None:
        ctx = _Ctx(invoked_subcommand=None)
        with self.assertRaises(typer.Exit) as exc_info:
            app_module.cli(
                ctx,
                config=None,
                paper=None,
                design=None,
                debug=False,
                debug_max_bytes=1024,
                debug_reveal_secrets=False,
                quiet=False,
                no_color=False,
                no_animations=False,
                init_config=False,
                version=False,
            )
        self.assertEqual(exc_info.exception.exit_code, 2)
        print_err.assert_called_once()
        prompt_home_action.assert_not_called()

    @mock.patch("ethernity.cli.bootstrap.app.run_recover_wizard", return_value=0)
    @mock.patch("ethernity.cli.bootstrap.app._run_cli", side_effect=lambda func, debug: func())
    @mock.patch("ethernity.cli.bootstrap.app.empty_recover_args", return_value=RecoverArgs())
    @mock.patch("ethernity.cli.bootstrap.app.prompt_home_action")
    @mock.patch("ethernity.cli.bootstrap.app.ui_screen_mode", return_value=contextlib.nullcontext())
    @mock.patch(
        "ethernity.cli.bootstrap.app.run_first_run_config_wizard",
        return_value=FirstRunOnboardingResult(applied_defaults=False, launch_action="recover"),
    )
    @mock.patch("ethernity.cli.bootstrap.app.load_cli_defaults", return_value=CliDefaults())
    @mock.patch("ethernity.cli.bootstrap.app._resolve_config_and_paper", return_value=("cfg", "A4"))
    @mock.patch("ethernity.cli.bootstrap.app.sys.stdout.isatty", return_value=True)
    @mock.patch("ethernity.cli.bootstrap.app.sys.stdin.isatty", return_value=True)
    @mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False)
    def test_cli_interactive_recover_route(
        self,
        _run_startup: mock.MagicMock,
        _stdin_tty: mock.MagicMock,
        _stdout_tty: mock.MagicMock,
        _resolve_config_and_paper: mock.MagicMock,
        _load_cli_defaults: mock.MagicMock,
        _run_first_run_config_wizard: mock.MagicMock,
        ui_screen_mode: mock.MagicMock,
        prompt_home_action: mock.MagicMock,
        _empty_recover_args: mock.MagicMock,
        _run_cli: mock.MagicMock,
        run_recover_wizard: mock.MagicMock,
    ) -> None:
        ctx = _Ctx(invoked_subcommand=None)
        app_module.cli(
            ctx,
            config=None,
            paper=None,
            design=None,
            debug=True,
            debug_max_bytes=1024,
            debug_reveal_secrets=True,
            quiet=False,
            no_color=False,
            no_animations=False,
            init_config=False,
            version=False,
        )
        ui_screen_mode.assert_not_called()
        prompt_home_action.assert_not_called()
        run_recover_wizard.assert_called_once()
        self.assertTrue(run_recover_wizard.call_args.kwargs["debug"])
        _empty_recover_args.assert_called_once_with(
            config="cfg",
            paper="A4",
            quiet=False,
            debug_max_bytes=1024,
            debug_reveal_secrets=True,
        )

    @mock.patch("ethernity.cli.bootstrap.app.run_mint_wizard", return_value=0)
    @mock.patch("ethernity.cli.bootstrap.app._run_cli", side_effect=lambda func, debug: func())
    @mock.patch("ethernity.cli.bootstrap.app.empty_mint_args")
    @mock.patch("ethernity.cli.bootstrap.app.prompt_home_action", return_value="mint")
    @mock.patch("ethernity.cli.bootstrap.app.ui_screen_mode", return_value=contextlib.nullcontext())
    @mock.patch("ethernity.cli.bootstrap.app.run_first_run_config_wizard", return_value=False)
    @mock.patch("ethernity.cli.bootstrap.app.load_cli_defaults", return_value=CliDefaults())
    @mock.patch("ethernity.cli.bootstrap.app._resolve_config_and_paper", return_value=("cfg", "A4"))
    @mock.patch("ethernity.cli.bootstrap.app.sys.stdout.isatty", return_value=True)
    @mock.patch("ethernity.cli.bootstrap.app.sys.stdin.isatty", return_value=True)
    @mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False)
    def test_cli_interactive_mint_route(
        self,
        _run_startup: mock.MagicMock,
        _stdin_tty: mock.MagicMock,
        _stdout_tty: mock.MagicMock,
        _resolve_config_and_paper: mock.MagicMock,
        _load_cli_defaults: mock.MagicMock,
        _run_first_run_config_wizard: mock.MagicMock,
        ui_screen_mode: mock.MagicMock,
        _prompt_home_action: mock.MagicMock,
        empty_mint_args: mock.MagicMock,
        _run_cli: mock.MagicMock,
        run_mint_wizard: mock.MagicMock,
    ) -> None:
        ctx = _Ctx(invoked_subcommand=None)
        empty_mint_args.return_value = mock.Mock()
        app_module.cli(
            ctx,
            config=None,
            paper=None,
            design="forge",
            debug=True,
            debug_max_bytes=1024,
            debug_reveal_secrets=False,
            quiet=False,
            no_color=False,
            no_animations=False,
            init_config=False,
            version=False,
        )
        ui_screen_mode.assert_called_once_with(quiet=False)
        empty_mint_args.assert_called_once_with(
            config="cfg",
            paper="A4",
            design="forge",
            quiet=False,
        )
        run_mint_wizard.assert_called_once()
        self.assertTrue(run_mint_wizard.call_args.kwargs["debug"])

    @mock.patch("ethernity.cli.bootstrap.app.run_extend_command", return_value=0)
    @mock.patch("ethernity.cli.bootstrap.app._run_cli", side_effect=lambda func, debug: func())
    @mock.patch("ethernity.cli.bootstrap.app._prompt_home_extend_args")
    @mock.patch("ethernity.cli.bootstrap.app.prompt_home_action", return_value="extend")
    @mock.patch("ethernity.cli.bootstrap.app.ui_screen_mode", return_value=contextlib.nullcontext())
    @mock.patch("ethernity.cli.bootstrap.app.run_first_run_config_wizard", return_value=False)
    @mock.patch("ethernity.cli.bootstrap.app.load_cli_defaults", return_value=CliDefaults())
    @mock.patch("ethernity.cli.bootstrap.app._resolve_config_and_paper", return_value=("cfg", "A4"))
    @mock.patch("ethernity.cli.bootstrap.app.sys.stdout.isatty", return_value=True)
    @mock.patch("ethernity.cli.bootstrap.app.sys.stdin.isatty", return_value=True)
    @mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False)
    def test_cli_interactive_extend_route(
        self,
        _run_startup: mock.MagicMock,
        _stdin_tty: mock.MagicMock,
        _stdout_tty: mock.MagicMock,
        _resolve_config_and_paper: mock.MagicMock,
        _load_cli_defaults: mock.MagicMock,
        _run_first_run_config_wizard: mock.MagicMock,
        ui_screen_mode: mock.MagicMock,
        _prompt_home_action: mock.MagicMock,
        prompt_home_extend_args: mock.MagicMock,
        _run_cli: mock.MagicMock,
        run_extend_command: mock.MagicMock,
    ) -> None:
        ctx = _Ctx(invoked_subcommand=None)
        extend_args = ExtendArgs(root_dir="/root", input_dir=["/input"], passphrase="secret")
        prompt_home_extend_args.return_value = extend_args
        app_module.cli(
            ctx,
            config=None,
            paper=None,
            design="forge",
            debug=True,
            debug_max_bytes=1024,
            debug_reveal_secrets=False,
            quiet=False,
            no_color=False,
            no_animations=False,
            init_config=False,
            version=False,
        )
        ui_screen_mode.assert_called_once_with(quiet=False)
        prompt_home_extend_args.assert_called_once_with(
            config="cfg",
            paper="A4",
            design="forge",
            quiet=False,
            extend_defaults=ExtendDefaults(),
        )
        run_extend_command.assert_called_once_with(extend_args, debug=True)

    @mock.patch("ethernity.cli.bootstrap.app.run_compact_command", return_value=0)
    @mock.patch("ethernity.cli.bootstrap.app._run_cli", side_effect=lambda func, debug: func())
    @mock.patch("ethernity.cli.bootstrap.app._prompt_home_compact_args")
    @mock.patch("ethernity.cli.bootstrap.app.prompt_home_action", return_value="compact")
    @mock.patch("ethernity.cli.bootstrap.app.ui_screen_mode", return_value=contextlib.nullcontext())
    @mock.patch("ethernity.cli.bootstrap.app.run_first_run_config_wizard", return_value=False)
    @mock.patch("ethernity.cli.bootstrap.app.load_cli_defaults", return_value=CliDefaults())
    @mock.patch("ethernity.cli.bootstrap.app._resolve_config_and_paper", return_value=("cfg", "A4"))
    @mock.patch("ethernity.cli.bootstrap.app.sys.stdout.isatty", return_value=True)
    @mock.patch("ethernity.cli.bootstrap.app.sys.stdin.isatty", return_value=True)
    @mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False)
    def test_cli_interactive_compact_route(
        self,
        _run_startup: mock.MagicMock,
        _stdin_tty: mock.MagicMock,
        _stdout_tty: mock.MagicMock,
        _resolve_config_and_paper: mock.MagicMock,
        _load_cli_defaults: mock.MagicMock,
        _run_first_run_config_wizard: mock.MagicMock,
        ui_screen_mode: mock.MagicMock,
        _prompt_home_action: mock.MagicMock,
        prompt_home_compact_args: mock.MagicMock,
        _run_cli: mock.MagicMock,
        run_compact_command: mock.MagicMock,
    ) -> None:
        ctx = _Ctx(invoked_subcommand=None)
        compact_args = CompactArgs(root_dir="/root", output_dir="/out", passphrase="secret")
        prompt_home_compact_args.return_value = compact_args
        app_module.cli(
            ctx,
            config=None,
            paper=None,
            design="forge",
            debug=False,
            debug_max_bytes=1024,
            debug_reveal_secrets=False,
            quiet=False,
            no_color=False,
            no_animations=False,
            init_config=False,
            version=False,
        )
        ui_screen_mode.assert_called_once_with(quiet=False)
        prompt_home_compact_args.assert_called_once_with(
            config="cfg",
            paper="A4",
            design="forge",
            quiet=False,
        )
        run_compact_command.assert_called_once_with(compact_args, debug=False)

    @mock.patch("ethernity.cli.bootstrap.app.run_wizard", return_value=0)
    @mock.patch("ethernity.cli.bootstrap.app._run_cli", side_effect=lambda func, debug: func())
    @mock.patch("ethernity.cli.bootstrap.app.prompt_home_action", return_value="backup")
    @mock.patch("ethernity.cli.bootstrap.app.ui_screen_mode", return_value=contextlib.nullcontext())
    @mock.patch("ethernity.cli.bootstrap.app.run_first_run_config_wizard", return_value=False)
    @mock.patch("ethernity.cli.bootstrap.app.load_cli_defaults", return_value=CliDefaults())
    @mock.patch("ethernity.cli.bootstrap.app._resolve_config_and_paper", return_value=("cfg", "A4"))
    @mock.patch("ethernity.cli.bootstrap.app.sys.stdout.isatty", return_value=True)
    @mock.patch("ethernity.cli.bootstrap.app.sys.stdin.isatty", return_value=True)
    @mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False)
    def test_cli_interactive_backup_route(
        self,
        _run_startup: mock.MagicMock,
        _stdin_tty: mock.MagicMock,
        _stdout_tty: mock.MagicMock,
        _resolve_config_and_paper: mock.MagicMock,
        _load_cli_defaults: mock.MagicMock,
        _run_first_run_config_wizard: mock.MagicMock,
        ui_screen_mode: mock.MagicMock,
        _prompt_home_action: mock.MagicMock,
        _run_cli: mock.MagicMock,
        run_wizard: mock.MagicMock,
    ) -> None:
        ctx = _Ctx(invoked_subcommand=None)
        app_module.cli(
            ctx,
            config=None,
            paper=None,
            design="forge",
            debug=False,
            debug_max_bytes=1024,
            debug_reveal_secrets=True,
            quiet=False,
            no_color=False,
            no_animations=False,
            init_config=False,
            version=False,
        )
        ui_screen_mode.assert_called_once_with(quiet=False)
        run_wizard.assert_called_once()
        self.assertEqual(run_wizard.call_args.kwargs["args"].design, "forge")
        self.assertTrue(run_wizard.call_args.kwargs["debug_reveal_secrets"])

    @mock.patch("ethernity.cli.bootstrap.app.run_wizard", return_value=0)
    @mock.patch("ethernity.cli.bootstrap.app._run_cli", side_effect=lambda func, debug: func())
    @mock.patch("ethernity.cli.bootstrap.app.prompt_home_action", return_value="backup")
    @mock.patch("ethernity.cli.bootstrap.app.ui_screen_mode", return_value=contextlib.nullcontext())
    @mock.patch("ethernity.cli.bootstrap.app.run_first_run_config_wizard", return_value=False)
    @mock.patch("ethernity.cli.bootstrap.app._resolve_config_and_paper", return_value=("cfg", "A4"))
    @mock.patch("ethernity.cli.bootstrap.app.sys.stdout.isatty", return_value=True)
    @mock.patch("ethernity.cli.bootstrap.app.sys.stdin.isatty", return_value=True)
    @mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False)
    def test_cli_interactive_backup_route_hydrates_saved_backup_defaults(
        self,
        _run_startup: mock.MagicMock,
        _stdin_tty: mock.MagicMock,
        _stdout_tty: mock.MagicMock,
        _resolve_config_and_paper: mock.MagicMock,
        _run_first_run_config_wizard: mock.MagicMock,
        ui_screen_mode: mock.MagicMock,
        _prompt_home_action: mock.MagicMock,
        _run_cli: mock.MagicMock,
        run_wizard: mock.MagicMock,
    ) -> None:
        ctx = _Ctx(invoked_subcommand=None)
        defaults = CliDefaults(
            backup=BackupDefaults(
                base_dir="/base",
                output_dir="/tmp/default-out",
                shard_threshold=2,
                shard_count=3,
                signing_key_mode="sharded",
                signing_key_shard_threshold=1,
                signing_key_shard_count=2,
            )
        )
        with mock.patch("ethernity.cli.bootstrap.app.load_cli_defaults", return_value=defaults):
            app_module.cli(
                ctx,
                config=None,
                paper=None,
                design="forge",
                debug=False,
                debug_max_bytes=1024,
                debug_reveal_secrets=True,
                quiet=False,
                no_color=False,
                no_animations=False,
                init_config=False,
                version=False,
            )

        ui_screen_mode.assert_called_once_with(quiet=False)
        run_wizard.assert_called_once()
        wizard_args = run_wizard.call_args.kwargs["args"]
        self.assertEqual(wizard_args.config, "cfg")
        self.assertEqual(wizard_args.paper, "A4")
        self.assertEqual(wizard_args.design, "forge")
        self.assertEqual(wizard_args.base_dir, "/base")
        self.assertEqual(wizard_args.output_dir, "/tmp/default-out")
        self.assertTrue(wizard_args.output_dir_existing_parent)
        self.assertEqual(wizard_args.shard_threshold, 2)
        self.assertEqual(wizard_args.shard_count, 3)
        self.assertEqual(wizard_args.signing_key_mode, "sharded")
        self.assertEqual(wizard_args.signing_key_shard_threshold, 1)
        self.assertEqual(wizard_args.signing_key_shard_count, 2)

    @mock.patch("ethernity.cli.bootstrap.app._run_kit_render", return_value=None)
    @mock.patch("ethernity.cli.bootstrap.app._run_cli", side_effect=lambda func, debug: func())
    @mock.patch("ethernity.cli.bootstrap.app.prompt_home_action", return_value="kit")
    @mock.patch("ethernity.cli.bootstrap.app.ui_screen_mode", return_value=contextlib.nullcontext())
    @mock.patch("ethernity.cli.bootstrap.app.run_first_run_config_wizard", return_value=False)
    @mock.patch("ethernity.cli.bootstrap.app.load_cli_defaults", return_value=CliDefaults())
    @mock.patch("ethernity.cli.bootstrap.app._resolve_config_and_paper", return_value=("cfg", "A4"))
    @mock.patch("ethernity.cli.bootstrap.app.sys.stdout.isatty", return_value=True)
    @mock.patch("ethernity.cli.bootstrap.app.sys.stdin.isatty", return_value=True)
    @mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False)
    def test_cli_interactive_kit_route(
        self,
        _run_startup: mock.MagicMock,
        _stdin_tty: mock.MagicMock,
        _stdout_tty: mock.MagicMock,
        _resolve_config_and_paper: mock.MagicMock,
        _load_cli_defaults: mock.MagicMock,
        _run_first_run_config_wizard: mock.MagicMock,
        ui_screen_mode: mock.MagicMock,
        _prompt_home_action: mock.MagicMock,
        _run_cli: mock.MagicMock,
        run_kit_render: mock.MagicMock,
    ) -> None:
        ctx = _Ctx(invoked_subcommand=None)
        app_module.cli(
            ctx,
            config=None,
            paper=None,
            design="forge",
            debug=False,
            debug_max_bytes=1024,
            debug_reveal_secrets=False,
            quiet=False,
            no_color=False,
            no_animations=False,
            init_config=False,
            version=False,
        )
        ui_screen_mode.assert_called_once_with(quiet=False)
        run_kit_render.assert_called_once_with(
            bundle=None,
            output=None,
            config_value="cfg",
            paper_value="A4",
            design_value="forge",
            variant_value="lean",
            qr_chunk_size=None,
            quiet_value=False,
        )

    @mock.patch("ethernity.cli.bootstrap.app.configure_ui")
    @mock.patch("ethernity.cli.bootstrap.app.sys.stdin.isatty", return_value=False)
    @mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False)
    def test_cli_applies_config_defaults_post_startup(
        self,
        _run_startup: mock.MagicMock,
        _stdin_tty: mock.MagicMock,
        configure_ui: mock.MagicMock,
    ) -> None:
        defaults = CliDefaults(
            ui=UiDefaults(quiet=True, no_color=True, no_animations=True),
            debug=DebugDefaults(max_bytes=4096),
        )
        with mock.patch("ethernity.cli.bootstrap.app.load_cli_defaults", return_value=defaults):
            ctx = _Ctx(invoked_subcommand="backup")
            app_module.cli(
                ctx,
                config=None,
                paper=None,
                design=None,
                debug=False,
                debug_max_bytes=None,
                quiet=False,
                no_color=False,
                no_animations=False,
                init_config=False,
                version=False,
            )

        self.assertIsNotNone(ctx.obj)
        ctx_obj = CliContextState() if ctx.obj is None else ctx.obj
        self.assertEqual(ctx_obj.quiet, True)
        self.assertEqual(ctx_obj.no_color, True)
        self.assertEqual(ctx_obj.no_animations, True)
        self.assertEqual(ctx_obj.debug_max_bytes, 4096)
        configure_ui.assert_called_once_with(no_color=True, no_animations=True)

    @mock.patch("ethernity.cli.bootstrap.app.configure_ui")
    @mock.patch("ethernity.cli.bootstrap.app.sys.stdin.isatty", return_value=False)
    @mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False)
    def test_cli_explicit_flags_override_config_defaults(
        self,
        _run_startup: mock.MagicMock,
        _stdin_tty: mock.MagicMock,
        configure_ui: mock.MagicMock,
    ) -> None:
        defaults = CliDefaults(
            ui=UiDefaults(quiet=False, no_color=False, no_animations=False),
            debug=DebugDefaults(max_bytes=256),
        )
        with mock.patch("ethernity.cli.bootstrap.app.load_cli_defaults", return_value=defaults):
            ctx = _Ctx(invoked_subcommand="backup")
            app_module.cli(
                ctx,
                config=None,
                paper=None,
                design=None,
                debug=False,
                debug_max_bytes=1234,
                quiet=True,
                no_color=True,
                no_animations=True,
                init_config=False,
                version=False,
            )

        self.assertIsNotNone(ctx.obj)
        ctx_obj = CliContextState() if ctx.obj is None else ctx.obj
        self.assertEqual(ctx_obj.quiet, True)
        self.assertEqual(ctx_obj.no_color, True)
        self.assertEqual(ctx_obj.no_animations, True)
        self.assertEqual(ctx_obj.debug_max_bytes, 1234)
        configure_ui.assert_called_once_with(no_color=True, no_animations=True)

    @mock.patch("ethernity.cli.bootstrap.app.configure_ui")
    @mock.patch("ethernity.cli.bootstrap.app.sys.stdin.isatty", return_value=False)
    @mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False)
    def test_cli_one_way_boolean_merge_uses_cli_or_config(
        self,
        _run_startup: mock.MagicMock,
        _stdin_tty: mock.MagicMock,
        configure_ui: mock.MagicMock,
    ) -> None:
        defaults = CliDefaults(
            ui=UiDefaults(quiet=True, no_color=True, no_animations=False),
            debug=DebugDefaults(max_bytes=None),
        )
        with mock.patch("ethernity.cli.bootstrap.app.load_cli_defaults", return_value=defaults):
            ctx = _Ctx(invoked_subcommand="backup")
            app_module.cli(
                ctx,
                config=None,
                paper=None,
                design=None,
                debug=False,
                debug_max_bytes=None,
                quiet=False,
                no_color=False,
                no_animations=True,
                init_config=False,
                version=False,
            )

        self.assertIsNotNone(ctx.obj)
        ctx_obj = CliContextState() if ctx.obj is None else ctx.obj
        self.assertEqual(ctx_obj.quiet, True)  # from config
        self.assertEqual(ctx_obj.no_color, True)  # from config
        self.assertEqual(ctx_obj.no_animations, True)  # from CLI flag
        configure_ui.assert_called_once_with(no_color=True, no_animations=True)

    @mock.patch("ethernity.cli.bootstrap.app.app")
    def test_main_dispatches(self, app_mock: mock.MagicMock) -> None:
        with mock.patch.object(app_module.sys, "argv", ["ethernity", "backup"]):
            app_module.main()
        app_mock.assert_called_once_with()

    @mock.patch("ethernity.cli.bootstrap.app.app")
    def test_main_uses_non_standalone_mode_for_top_level_api_invocations(
        self,
        app_mock: mock.MagicMock,
    ) -> None:
        with mock.patch.object(app_module.sys, "argv", ["ethernity", "api"]):
            app_module.main()
        app_mock.assert_called_once_with(standalone_mode=False)


if __name__ == "__main__":
    unittest.main()
