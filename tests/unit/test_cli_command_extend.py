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

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import typer
from typer.testing import CliRunner

import ethernity.cli as cli
from ethernity.cli.features.extend import command as extend_command
from ethernity.cli.features.extend.service import EXTENSION_TOO_LARGE, PublishedExtensionResult
from ethernity.cli.shared.ndjson import ApiCommandError
from ethernity.cli.shared.types import CliContextState
from ethernity.config import (
    BackupDefaults,
    CliDefaults,
    DebugDefaults,
    RecoverDefaults,
    RuntimeDefaults,
    UiDefaults,
)


class TestExtendCommand(unittest.TestCase):
    def _ctx(self, **values: object) -> object:
        return mock.Mock(obj=CliContextState(**values))

    @mock.patch("ethernity.cli.features.extend.command.run_extend_command", return_value=0)
    @mock.patch(
        "ethernity.cli.features.extend.command._run_cli", side_effect=lambda func, debug: func()
    )
    @mock.patch(
        "ethernity.cli.features.extend.command._resolve_config_and_paper",
        return_value=("ctx.toml", "LETTER"),
    )
    def test_extend_command_resolves_context_and_defaults(
        self,
        _resolve_config_and_paper: mock.MagicMock,
        _run_cli: mock.MagicMock,
        run_extend_command: mock.MagicMock,
    ) -> None:
        ctx = self._ctx(
            design="forge",
            quiet=False,
            debug=True,
            backup_defaults=BackupDefaults(
                base_dir="./vault",
                shard_threshold=2,
                shard_count=3,
                signing_key_mode="sharded",
                signing_key_shard_threshold=2,
                signing_key_shard_count=3,
            ),
        )
        extend_command.extend(
            ctx,
            root_dir=Path("/tmp/root"),
            input=[Path("updated.txt")],
            input_dir=None,
            base_dir=None,
            layout_debug_dir="/tmp/layout",
            qr_chunk_size=640,
            passphrase="secret",
            shard_fallback_file=None,
            shard_payloads_file=None,
            shard_scan=None,
            unlock_policy=None,
            shard_threshold=None,
            shard_count=None,
            signing_key_mode=None,
            signing_key_shard_threshold=None,
            signing_key_shard_count=None,
            config=None,
            paper=None,
            design=None,
            debug=False,
            quiet=False,
        )

        args = run_extend_command.call_args.args[0]
        self.assertEqual(args.config, "ctx.toml")
        self.assertEqual(args.paper, "LETTER")
        self.assertEqual(args.design, "forge")
        self.assertEqual(args.root_dir, "/tmp/root")
        self.assertEqual(args.input, ["updated.txt"])
        self.assertEqual(args.base_dir, "./vault")
        self.assertEqual(args.layout_debug_dir, "/tmp/layout")
        self.assertEqual(args.qr_chunk_size, 640)
        self.assertEqual(args.passphrase, "secret")
        self.assertEqual(args.shard_scan, [])
        self.assertIsNone(args.unlock_policy)
        self.assertIsNone(args.shard_threshold)
        self.assertIsNone(args.shard_count)
        self.assertIsNone(args.signing_key_mode)
        self.assertIsNone(args.signing_key_shard_threshold)
        self.assertIsNone(args.signing_key_shard_count)
        self.assertTrue(run_extend_command.call_args.kwargs["debug"])

    @mock.patch("ethernity.cli.features.extend.command.console_err")
    def test_extend_command_requires_explicit_scope(self, console_err: mock.MagicMock) -> None:
        ctx = self._ctx(quiet=False, debug=False)

        with self.assertRaises(typer.Exit) as raised:
            extend_command.extend(
                ctx,
                root_dir=Path("/tmp/root"),
                input=None,
                input_dir=None,
                base_dir=None,
                layout_debug_dir=None,
                qr_chunk_size=None,
                passphrase=None,
                shard_fallback_file=None,
                shard_payloads_file=None,
                shard_scan=None,
                unlock_policy=None,
                shard_threshold=None,
                shard_count=None,
                signing_key_mode=None,
                signing_key_shard_threshold=None,
                signing_key_shard_count=None,
                config=None,
                paper=None,
                design=None,
                debug=False,
                quiet=False,
            )

        self.assertEqual(raised.exception.exit_code, 2)
        console_err.print.assert_called_once()

    @mock.patch("ethernity.cli.features.extend.command._print_completion_actions")
    @mock.patch("ethernity.cli.features.extend.command._print_extend_summary")
    @mock.patch("ethernity.cli.features.extend.command.run_extend")
    def test_run_extend_command_prints_summary(
        self,
        run_extend: mock.MagicMock,
        print_extend_summary: mock.MagicMock,
        print_completion_actions: mock.MagicMock,
    ) -> None:
        result = PublishedExtensionResult(
            index=2,
            doc_id=b"\xaa" * 16,
            doc_hash=b"\xbb" * 32,
            final_dir=Path("/tmp/root/extensions/02"),
            qr_document_path=Path("/tmp/root/extensions/02/qr_document-02-aa.pdf"),
            recovery_document_path=Path("/tmp/root/extensions/02/recovery_document-02-aa.pdf"),
            recovery_kit_index_path=None,
            shard_paths=(Path("/tmp/root/extensions/02/shard-1.pdf"),),
            signing_key_shard_paths=(),
        )
        run_extend.return_value = result

        exit_code = extend_command.run_extend_command(
            extend_command.ExtendArgs(root_dir="/tmp/root", input=["updated.txt"], quiet=False)
        )

        self.assertEqual(exit_code, 0)
        print_extend_summary.assert_called_once_with(result, quiet=False)
        print_completion_actions.assert_called_once_with(result, quiet=False)

    @mock.patch("ethernity.cli.features.extend.command.print_completion_panel")
    def test_completion_actions_mentions_reused_root_shards(
        self,
        print_completion_panel: mock.MagicMock,
    ) -> None:
        result = PublishedExtensionResult(
            index=2,
            doc_id=b"\xaa" * 16,
            doc_hash=b"\xbb" * 32,
            final_dir=Path("/tmp/root/extensions/02"),
            qr_document_path=Path("/tmp/root/extensions/02/qr_document-02-aa.pdf"),
            recovery_document_path=Path("/tmp/root/extensions/02/recovery_document-02-aa.pdf"),
            recovery_kit_index_path=None,
            shard_paths=(),
            signing_key_shard_paths=(),
            root_passphrase_shard_threshold=2,
            root_passphrase_shard_count=3,
        )

        extend_command._print_completion_actions(result, quiet=False)

        actions = print_completion_panel.call_args.args[1]
        self.assertTrue(
            any("root passphrase shard quorum (2 of 3)" in action for action in actions)
        )

    def test_register(self) -> None:
        app = typer.Typer()
        extend_command.register(app)
        self.assertGreater(len(app.registered_commands), 0)

    def test_extend_dry_run_rejects_too_large_preview(self) -> None:
        args = extend_command.ExtendArgs(root_dir="/tmp/root", input=["updated.txt"], quiet=True)
        with (
            mock.patch(
                "ethernity.cli.features.extend.command.prepare_extend_run",
                return_value=SimpleNamespace(
                    args=args,
                    inspection=SimpleNamespace(root_dir="/tmp/root"),
                    next_index=2,
                ),
            ),
            mock.patch("ethernity.cli.features.extend.command.preflight_extension_publish_target"),
            mock.patch("ethernity.cli.features.extend.command.resolve_extend_runtime"),
            mock.patch(
                "ethernity.cli.features.extend.command.encrypt_prepared_extension_document",
                return_value=SimpleNamespace(ciphertext=b"xx"),
            ),
            mock.patch("ethernity.cli.features.extend.command.MAX_CIPHERTEXT_BYTES", 1),
        ):
            with self.assertRaises(ApiCommandError) as ctx:
                extend_command.run_extend_dry_run_command(args)

        self.assertEqual(ctx.exception.code, EXTENSION_TOO_LARGE)

    def test_extend_dry_run_validates_layout_debug_dir_without_creating_it(self) -> None:
        args = extend_command.ExtendArgs(
            root_dir="/tmp/request-root",
            input=["updated.txt"],
            layout_debug_dir="/tmp/layout-debug",
            quiet=True,
        )
        prepared = SimpleNamespace(
            args=args,
            inspection=SimpleNamespace(root_dir="/tmp/prepared-root"),
            next_index=1,
            parent_doc_hash=b"\x11" * 32,
            changed_paths=(),
            new_paths=(),
            unchanged_paths=(),
        )
        runtime = SimpleNamespace(
            qr_chunk_size=512,
            passphrase=extend_command.PlaintextPassphrase(),
            signing_key=object(),
            kit_index_template_path=None,
        )
        encrypted = SimpleNamespace(
            ciphertext=b"x",
            built=SimpleNamespace(
                stats=SimpleNamespace(reused_chunks=1, new_chunks=2),
            ),
        )
        with (
            mock.patch(
                "ethernity.cli.features.extend.command.prepare_extend_run",
                return_value=prepared,
            ),
            mock.patch(
                "ethernity.cli.features.extend.command.preflight_extension_publish_target"
            ) as preflight,
            mock.patch(
                "ethernity.cli.features.extend.command.resolve_extend_runtime",
                return_value=runtime,
            ) as resolve_runtime,
            mock.patch(
                "ethernity.cli.features.extend.command.encrypt_prepared_extension_document",
                return_value=encrypted,
            ),
        ):
            result = extend_command.run_extend_dry_run_command(args)

        self.assertEqual(result, 0)
        preflight.assert_called_once_with("/tmp/prepared-root", index=1)
        resolve_runtime.assert_called_once_with(prepared, create_layout_debug_dir=False)

    def test_extend_dry_run_reports_invalid_publish_target(self) -> None:
        args = extend_command.ExtendArgs(root_dir="/tmp/root", input=["updated.txt"], quiet=True)
        prepared = SimpleNamespace(
            args=args,
            inspection=SimpleNamespace(root_dir="/tmp/root"),
            next_index=3,
        )
        with (
            mock.patch(
                "ethernity.cli.features.extend.command.prepare_extend_run",
                return_value=prepared,
            ),
            mock.patch(
                "ethernity.cli.features.extend.command.preflight_extension_publish_target",
                side_effect=ValueError("canonical extension directory already exists: 03"),
            ),
        ):
            with self.assertRaises(ApiCommandError) as ctx:
                extend_command.run_extend_dry_run_command(args)

        self.assertEqual(ctx.exception.code, "EXTENSION_PUBLISH_TARGET_INVALID")
        self.assertEqual(ctx.exception.details, {"stage": "publish_target"})

    @mock.patch("ethernity.cli.features.extend.command.run_extend_command", return_value=0)
    @mock.patch(
        "ethernity.cli.features.extend.command._run_cli", side_effect=lambda func, debug: func()
    )
    @mock.patch(
        "ethernity.cli.features.extend.command._resolve_config_and_paper",
        return_value=("ctx.toml", "LETTER"),
    )
    def test_extend_command_passes_unlock_policy(
        self,
        _resolve_config_and_paper: mock.MagicMock,
        _run_cli: mock.MagicMock,
        run_extend_command: mock.MagicMock,
    ) -> None:
        extend_command.extend(
            self._ctx(
                quiet=False,
                debug=False,
                backup_defaults=BackupDefaults(
                    shard_threshold=2,
                    shard_count=3,
                    signing_key_mode="sharded",
                    signing_key_shard_threshold=2,
                    signing_key_shard_count=3,
                ),
            ),
            root_dir=Path("/tmp/root"),
            input=[Path("updated.txt")],
            input_dir=None,
            base_dir=None,
            layout_debug_dir=None,
            qr_chunk_size=None,
            passphrase=None,
            shard_fallback_file=None,
            shard_payloads_file=None,
            shard_scan=None,
            unlock_policy="reuse-root",
            shard_threshold=None,
            shard_count=None,
            signing_key_mode=None,
            signing_key_shard_threshold=None,
            signing_key_shard_count=None,
            config=None,
            paper=None,
            design=None,
            debug=False,
            quiet=False,
        )

        args = run_extend_command.call_args.args[0]
        self.assertEqual(args.unlock_policy, "reuse-root")
        self.assertIsNone(args.shard_threshold)
        self.assertIsNone(args.shard_count)
        self.assertIsNone(args.signing_key_mode)
        self.assertIsNone(args.signing_key_shard_threshold)
        self.assertIsNone(args.signing_key_shard_count)

    @mock.patch("ethernity.cli.features.extend.command.run_extend_command", return_value=0)
    @mock.patch(
        "ethernity.cli.features.extend.command._run_cli", side_effect=lambda func, debug: func()
    )
    @mock.patch(
        "ethernity.cli.features.extend.command._resolve_config_and_paper",
        return_value=("ctx.toml", "LETTER"),
    )
    def test_extend_command_passes_shard_unlock_inputs(
        self,
        _resolve_config_and_paper: mock.MagicMock,
        _run_cli: mock.MagicMock,
        run_extend_command: mock.MagicMock,
    ) -> None:
        extend_command.extend(
            self._ctx(quiet=False, debug=False, backup_defaults=BackupDefaults()),
            root_dir=Path("/tmp/root"),
            input=[Path("updated.txt")],
            input_dir=None,
            base_dir=None,
            layout_debug_dir=None,
            qr_chunk_size=None,
            passphrase=None,
            shard_fallback_file=["manual.txt"],
            shard_payloads_file=["payloads.txt"],
            shard_scan=["scan.pdf"],
            unlock_policy=None,
            shard_threshold=None,
            shard_count=None,
            signing_key_mode=None,
            signing_key_shard_threshold=None,
            signing_key_shard_count=None,
            config=None,
            paper=None,
            design=None,
            debug=False,
            quiet=False,
        )

        args = run_extend_command.call_args.args[0]
        self.assertEqual(args.shard_fallback_file, ["manual.txt"])
        self.assertEqual(args.shard_payloads_file, ["payloads.txt"])
        self.assertEqual(args.shard_scan, ["scan.pdf"])

    @mock.patch("ethernity.cli.features.extend.command.run_extend_command", return_value=0)
    @mock.patch("ethernity.cli.features.extend.command.run_extend_dry_run_command", return_value=0)
    @mock.patch(
        "ethernity.cli.features.extend.command._run_cli", side_effect=lambda func, debug: func()
    )
    @mock.patch(
        "ethernity.cli.features.extend.command._resolve_config_and_paper",
        return_value=("ctx.toml", "LETTER"),
    )
    def test_extend_command_dry_run_uses_preview_command(
        self,
        _resolve_config_and_paper: mock.MagicMock,
        _run_cli: mock.MagicMock,
        run_extend_dry_run_command: mock.MagicMock,
        run_extend_command: mock.MagicMock,
    ) -> None:
        extend_command.extend(
            self._ctx(quiet=False, debug=False, backup_defaults=BackupDefaults()),
            root_dir=Path("/tmp/root"),
            input=[Path("updated.txt")],
            input_dir=None,
            base_dir=None,
            layout_debug_dir=None,
            qr_chunk_size=None,
            passphrase="secret",
            shard_fallback_file=None,
            shard_payloads_file=None,
            shard_scan=None,
            unlock_policy=None,
            shard_threshold=None,
            shard_count=0,
            signing_key_mode=None,
            signing_key_shard_threshold=None,
            signing_key_shard_count=None,
            quiet=False,
            dry_run=True,
            config=None,
            paper=None,
            design=None,
            debug=False,
        )

        run_extend_dry_run_command.assert_called_once()
        run_extend_command.assert_not_called()


class TestExtendCliApp(unittest.TestCase):
    runner = CliRunner()

    def test_extend_bootstraps_operator_defaults_from_cli_config(self) -> None:
        captured: dict[str, object] = {}

        def _capture_args(args: extend_command.ExtendArgs, *, debug: bool = False) -> int:
            captured["base_dir"] = args.base_dir
            captured["root_dir"] = args.root_dir
            captured["input"] = list(args.input or [])
            captured["debug"] = debug
            return 0

        defaults = CliDefaults(
            backup=BackupDefaults(base_dir="./vault", shard_threshold=2),
            recover=RecoverDefaults(),
            ui=UiDefaults(),
            debug=DebugDefaults(),
            runtime=RuntimeDefaults(),
        )

        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            with mock.patch("ethernity.cli.bootstrap.app.load_cli_defaults", return_value=defaults):
                with mock.patch(
                    "ethernity.cli.features.extend.command.run_extend_command",
                    side_effect=_capture_args,
                ):
                    result = self.runner.invoke(
                        cli.app,
                        ["extend", "--root-dir", "/tmp/root", "--input", "-"],
                        input="payload",
                    )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(captured["base_dir"], "./vault")
        self.assertEqual(captured["root_dir"], "/tmp/root")
        self.assertEqual(captured["input"], ["-"])
