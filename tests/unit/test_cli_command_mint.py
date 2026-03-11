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

from __future__ import annotations

import contextlib
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

import typer

from ethernity.cli.commands import mint as mint_command
from ethernity.cli.core.types import CliContextState, MintArgs
from ethernity.cli.flows import mint as mint_flow
from ethernity.crypto.sharding import KEY_TYPE_SIGNING_SEED


class TestMintCommand(unittest.TestCase):
    def _ctx(self, **values: object) -> mock.Mock:
        return mock.Mock(obj=CliContextState(**cast(dict[str, Any], values)))

    def _call_mint(self, ctx: mock.Mock, **overrides: object) -> None:
        options = {
            "fallback_file": None,
            "payloads_file": None,
            "scan": None,
            "passphrase": None,
            "shard_fallback_file": None,
            "shard_dir": None,
            "shard_payloads_file": None,
            "auth_fallback_file": None,
            "auth_payloads_file": None,
            "signing_key_shard_fallback_file": None,
            "signing_key_shard_dir": None,
            "signing_key_shard_payloads_file": None,
            "output_dir": None,
            "layout_debug_dir": None,
            "shard_threshold": None,
            "shard_count": None,
            "signing_key_shard_threshold": None,
            "signing_key_shard_count": None,
            "passphrase_replacement_count": None,
            "signing_key_replacement_count": None,
            "mint_passphrase_shards": True,
            "mint_signing_key_shards": True,
            "config": None,
            "paper": None,
            "design": None,
            "quiet": False,
        }
        options.update(overrides)
        mint_command.mint(cast(Any, ctx), **options)

    def test_expand_shard_dir(self) -> None:
        self.assertEqual(mint_command._expand_shard_dir(None, label="shard"), [])
        with self.assertRaises(typer.BadParameter):
            mint_command._expand_shard_dir("/definitely/missing", label="shard")

    @mock.patch("ethernity.cli.commands.mint.run_mint_command", return_value=0)
    @mock.patch("ethernity.cli.commands.mint._run_cli", side_effect=lambda func, debug: func())
    @mock.patch("ethernity.cli.commands.mint._expand_shard_dir")
    @mock.patch("ethernity.cli.commands.mint._resolve_config_and_paper", return_value=("cfg", "A4"))
    def test_mint_merges_input_dirs_and_context(
        self,
        _resolve_config_and_paper: mock.MagicMock,
        expand_shard_dir: mock.MagicMock,
        _run_cli: mock.MagicMock,
        run_mint_command: mock.MagicMock,
    ) -> None:
        expand_shard_dir.side_effect = [["passphrase-dir.txt"], ["signing-dir.txt"]]
        ctx = self._ctx(quiet=False, debug=True, design="sentinel")
        self._call_mint(
            ctx,
            shard_fallback_file=["manual-passphrase.txt"],
            shard_dir="passphrase-shards",
            signing_key_shard_fallback_file=["manual-signing.txt"],
            signing_key_shard_dir="signing-shards",
            shard_threshold=2,
            shard_count=3,
            passphrase_replacement_count=1,
            signing_key_replacement_count=2,
        )
        args = run_mint_command.call_args.args[0]
        self.assertIsInstance(args, MintArgs)
        self.assertEqual(args.config, "cfg")
        self.assertEqual(args.paper, "A4")
        self.assertEqual(args.design, "sentinel")
        self.assertEqual(args.shard_fallback_file, ["manual-passphrase.txt", "passphrase-dir.txt"])
        self.assertEqual(
            args.signing_key_shard_fallback_file,
            ["manual-signing.txt", "signing-dir.txt"],
        )
        self.assertEqual(args.passphrase_replacement_count, 1)
        self.assertEqual(args.signing_key_replacement_count, 2)
        self.assertEqual(run_mint_command.call_args.kwargs["debug"], True)

    def test_register(self) -> None:
        app = typer.Typer()
        mint_command.register(app)
        self.assertGreater(len(app.registered_commands), 0)


class TestMintFlow(unittest.TestCase):
    def test_validate_mint_args_requires_output_selection(self) -> None:
        args = MintArgs(
            payloads_file="qr.txt",
            passphrase="passphrase",
            mint_passphrase_shards=False,
            mint_signing_key_shards=False,
        )
        with self.assertRaisesRegex(ValueError, "at least one shard document type"):
            mint_flow._validate_mint_args(args)

    def test_validate_mint_args_replacement_requires_matching_inputs(self) -> None:
        args = MintArgs(
            payloads_file="qr.txt",
            passphrase="passphrase",
            passphrase_replacement_count=1,
            mint_signing_key_shards=False,
        )
        with self.assertRaisesRegex(ValueError, "existing passphrase shard inputs"):
            mint_flow._validate_mint_args(args)

    @mock.patch(
        "ethernity.cli.flows.mint._replacement_payloads_from_frames",
        side_effect=[
            mint_flow._ReplacementShardResolution(provided_count=1, threshold=2),
            mint_flow._ReplacementShardResolution(),
        ],
    )
    @mock.patch("ethernity.cli.flows.mint._ensure_mint_output_dir", return_value="/tmp/minted")
    @mock.patch("ethernity.cli.flows.mint.RenderService")
    @mock.patch("ethernity.cli.flows.mint.derive_public_key", return_value=b"p" * 32)
    def test_mint_from_plan_rejects_under_quorum_replacement_request(
        self,
        _derive_public_key: mock.MagicMock,
        _render_service: mock.MagicMock,
        _ensure_mint_output_dir: mock.MagicMock,
        _replacement_payloads_from_frames: mock.MagicMock,
    ) -> None:
        args = MintArgs(
            passphrase_replacement_count=1,
            mint_signing_key_shards=False,
            quiet=True,
        )
        plan = SimpleNamespace(
            ciphertext=b"ciphertext",
            doc_id=b"d" * 16,
            doc_hash=b"h" * 32,
            passphrase="mint-passphrase",
            auth_payload=SimpleNamespace(sign_pub=b"p" * 32),
        )
        config = SimpleNamespace(
            cli_defaults=SimpleNamespace(backup=SimpleNamespace(qr_payload_codec="raw"))
        )

        with self.assertRaisesRegex(
            ValueError,
            r"need at least 2 validated shard\(s\), got 1",
        ):
            mint_flow._mint_from_plan(
                plan=plan,
                config=config,
                args=args,
                passphrase_shard_frames=[mock.Mock()],
                signing_key_frames=[],
                manifest_signing_seed=b"s" * 32,
                debug=False,
            )
        _ensure_mint_output_dir.assert_not_called()

    @mock.patch("ethernity.cli.flows.mint._print_completion_actions")
    @mock.patch("ethernity.cli.flows.mint.print_mint_summary")
    @mock.patch(
        "ethernity.cli.flows.mint._mint_from_plan",
        return_value=SimpleNamespace(
            doc_id=b"d" * 16,
            output_dir="mint-dd",
            shard_paths=(),
            signing_key_shard_paths=(),
            signing_key_source="embedded signing seed",
        ),
    )
    @mock.patch("ethernity.cli.flows.mint._signing_key_shard_frames_from_args", return_value=[])
    @mock.patch(
        "ethernity.cli.flows.mint.build_recovery_plan",
        return_value=SimpleNamespace(
            ciphertext=b"ciphertext",
            doc_id=b"d" * 16,
            doc_hash=b"h" * 32,
            passphrase="mint-passphrase",
            auth_payload=SimpleNamespace(sign_pub=b"p" * 32),
        ),
    )
    @mock.patch(
        "ethernity.cli.flows.mint._shard_frames_from_args",
        return_value=([mock.Mock()], ["old-shard.txt"], ["old-shard.payload"]),
    )
    @mock.patch("ethernity.cli.flows.mint._extra_auth_frames_from_args", return_value=[])
    @mock.patch(
        "ethernity.cli.flows.mint._frames_from_args", return_value=([], "QR payloads", "qr.txt")
    )
    @mock.patch(
        "ethernity.cli.flows.mint.apply_template_design", side_effect=lambda config, design: config
    )
    @mock.patch("ethernity.cli.flows.mint.load_app_config", return_value=SimpleNamespace())
    def test_run_mint_command_ignores_shard_inputs_for_recovery_when_passphrase_is_provided(
        self,
        _load_app_config: mock.MagicMock,
        _apply_template_design: mock.MagicMock,
        _frames_from_args: mock.MagicMock,
        _extra_auth_frames_from_args: mock.MagicMock,
        _shard_frames_from_args: mock.MagicMock,
        build_recovery_plan: mock.MagicMock,
        _signing_key_shard_frames_from_args: mock.MagicMock,
        _mint_from_plan: mock.MagicMock,
        _print_mint_summary: mock.MagicMock,
        _print_completion_actions: mock.MagicMock,
    ) -> None:
        args = MintArgs(
            payloads_file="qr.txt",
            passphrase="passphrase",
            shard_payloads_file=["old-shard.payload"],
            passphrase_replacement_count=1,
            mint_signing_key_shards=False,
            quiet=True,
        )

        result = mint_flow.run_mint_command(args, debug=False)

        self.assertEqual(result, 0)
        self.assertEqual(build_recovery_plan.call_args.kwargs["shard_frames"], [])
        self.assertEqual(build_recovery_plan.call_args.kwargs["shard_fallback_files"], [])
        self.assertEqual(build_recovery_plan.call_args.kwargs["shard_payloads_file"], [])

    @mock.patch("ethernity.cli.flows.mint.print_completion_panel")
    @mock.patch("ethernity.cli.flows.mint.print_mint_summary")
    @mock.patch("ethernity.cli.flows.mint._ensure_mint_output_dir", return_value="/tmp/minted")
    @mock.patch("ethernity.cli.flows.mint._render_shard")
    @mock.patch("ethernity.cli.flows.mint.split_signing_seed")
    @mock.patch("ethernity.cli.flows.mint.split_passphrase")
    @mock.patch("ethernity.cli.flows.mint._signing_key_shard_frames_from_args", return_value=[])
    @mock.patch(
        "ethernity.cli.flows.mint.decode_envelope",
        return_value=(SimpleNamespace(signing_seed=b"s" * 32), b"payload"),
    )
    @mock.patch("ethernity.cli.flows.mint.decrypt_bytes", return_value=b"plaintext")
    @mock.patch(
        "ethernity.cli.flows.mint.build_recovery_plan",
        return_value=SimpleNamespace(
            ciphertext=b"ciphertext",
            doc_id=b"d" * 16,
            doc_hash=b"h" * 32,
            passphrase="mint-passphrase",
            auth_payload=SimpleNamespace(sign_pub=b"p" * 32),
        ),
    )
    @mock.patch("ethernity.cli.flows.mint._shard_frames_from_args", return_value=([], [], []))
    @mock.patch("ethernity.cli.flows.mint._extra_auth_frames_from_args", return_value=[])
    @mock.patch(
        "ethernity.cli.flows.mint._frames_from_args", return_value=([], "QR payloads", "qr.txt")
    )
    @mock.patch(
        "ethernity.cli.flows.mint.apply_template_design", side_effect=lambda config, design: config
    )
    @mock.patch(
        "ethernity.cli.flows.mint.load_app_config",
        return_value=SimpleNamespace(
            shard_template_path=Path("shard.html.j2"),
            signing_key_shard_template_path=Path("signing-shard.html.j2"),
            cli_defaults=SimpleNamespace(backup=SimpleNamespace(qr_payload_codec="raw")),
        ),
    )
    @mock.patch("ethernity.cli.flows.mint.derive_public_key", return_value=b"p" * 32)
    def test_run_mint_command_uses_embedded_signing_seed(
        self,
        derive_public_key: mock.MagicMock,
        _load_app_config: mock.MagicMock,
        _apply_template_design: mock.MagicMock,
        _frames_from_args: mock.MagicMock,
        _extra_auth_frames_from_args: mock.MagicMock,
        _shard_frames_from_args: mock.MagicMock,
        _build_recovery_plan: mock.MagicMock,
        _decrypt_bytes: mock.MagicMock,
        _decode_envelope: mock.MagicMock,
        _signing_key_shard_frames_from_args: mock.MagicMock,
        split_passphrase: mock.MagicMock,
        split_signing_seed: mock.MagicMock,
        render_shard: mock.MagicMock,
        _ensure_mint_output_dir: mock.MagicMock,
        print_mint_summary: mock.MagicMock,
        print_completion_panel: mock.MagicMock,
    ) -> None:
        split_passphrase.return_value = [SimpleNamespace(share_index=1, share_count=2)]
        split_signing_seed.return_value = [SimpleNamespace(share_index=1, share_count=2)]
        render_shard.side_effect = ["/tmp/minted/shard-1.pdf", "/tmp/minted/signing-1.pdf"]
        args = MintArgs(
            payloads_file="qr.txt",
            passphrase="passphrase",
            shard_threshold=2,
            shard_count=2,
            quiet=True,
        )
        result = mint_flow.run_mint_command(args, debug=False)
        self.assertEqual(result, 0)
        split_passphrase.assert_called_once()
        split_signing_seed.assert_called_once()
        self.assertEqual(render_shard.call_count, 2)
        print_mint_summary.assert_called_once()
        print_completion_panel.assert_not_called()

    @mock.patch("ethernity.cli.flows.mint._signing_seed_from_shard_frames", return_value=b"s" * 32)
    def test_resolve_signing_authority_uses_signing_key_shards_when_sealed(
        self,
        signing_seed_from_frames: mock.MagicMock,
    ) -> None:
        seed, source = mint_flow._resolve_signing_authority(
            manifest_signing_seed=None,
            signing_key_frames=[mock.Mock()],
            doc_id=b"d" * 16,
            doc_hash=b"h" * 32,
            expected_sign_pub=b"p" * 32,
        )
        self.assertEqual(seed, b"s" * 32)
        self.assertEqual(source, "signing-key shards")
        signing_seed_from_frames.assert_called_once()

    @mock.patch("ethernity.cli.flows.mint._print_completion_actions")
    @mock.patch("ethernity.cli.flows.mint.print_mint_summary")
    @mock.patch(
        "ethernity.cli.flows.mint._mint_from_plan",
        return_value=SimpleNamespace(
            doc_id=b"d" * 16,
            output_dir="mint-dd",
            shard_paths=(),
            signing_key_shard_paths=(),
            signing_key_source="embedded signing seed",
        ),
    )
    @mock.patch(
        "ethernity.cli.flows.mint.decode_envelope",
        return_value=(SimpleNamespace(signing_seed=b"s" * 32), b"payload"),
    )
    @mock.patch("ethernity.cli.flows.mint.decrypt_bytes", return_value=b"plaintext")
    @mock.patch(
        "ethernity.cli.flows.mint.build_recovery_plan",
        return_value=SimpleNamespace(
            ciphertext=b"ciphertext",
            doc_id=b"d" * 16,
            doc_hash=b"h" * 32,
            passphrase="mint-passphrase",
            auth_payload=SimpleNamespace(sign_pub=b"p" * 32),
        ),
    )
    @mock.patch("ethernity.cli.flows.mint._prompt_key_material")
    @mock.patch(
        "ethernity.cli.flows.mint.prompt_recovery_input_interactive",
        return_value=([], "QR payloads", "qr.txt"),
    )
    @mock.patch("ethernity.cli.flows.mint._prompt_quorum_choice")
    @mock.patch("ethernity.cli.flows.mint.prompt_yes_no", side_effect=[True, False])
    @mock.patch(
        "ethernity.cli.flows.mint.apply_template_design", side_effect=lambda config, design: config
    )
    @mock.patch("ethernity.cli.flows.mint.load_app_config", return_value=SimpleNamespace())
    @mock.patch(
        "ethernity.cli.flows.mint.wizard_stage",
        side_effect=lambda *_args, **_kwargs: contextlib.nullcontext(),
    )
    @mock.patch(
        "ethernity.cli.flows.mint.wizard_flow",
        side_effect=lambda *_args, **_kwargs: contextlib.nullcontext(),
    )
    @mock.patch(
        "ethernity.cli.flows.mint.ui_screen_mode",
        side_effect=lambda **_kwargs: contextlib.nullcontext(),
    )
    @mock.patch("ethernity.cli.flows.mint.sys.stdout.isatty", return_value=True)
    @mock.patch("ethernity.cli.flows.mint.sys.stdin.isatty", return_value=True)
    def test_run_mint_wizard_uses_default_output_directory(
        self,
        _stdin_isatty: mock.MagicMock,
        _stdout_isatty: mock.MagicMock,
        _ui_screen_mode: mock.MagicMock,
        _wizard_flow: mock.MagicMock,
        _wizard_stage: mock.MagicMock,
        _load_app_config: mock.MagicMock,
        _apply_template_design: mock.MagicMock,
        prompt_yes_no: mock.MagicMock,
        prompt_quorum_choice: mock.MagicMock,
        _prompt_recovery_input_interactive: mock.MagicMock,
        prompt_key_material: mock.MagicMock,
        _build_recovery_plan: mock.MagicMock,
        _decrypt_bytes: mock.MagicMock,
        _decode_envelope: mock.MagicMock,
        mint_from_plan: mock.MagicMock,
        print_mint_summary: mock.MagicMock,
        print_completion_actions: mock.MagicMock,
    ) -> None:
        prompt_key_material.return_value = ("passphrase", [], None, [])
        prompt_quorum_choice.return_value = SimpleNamespace(threshold=2, shares=3)

        result = mint_flow.run_mint_wizard(MintArgs(quiet=True), debug=False, show_header=False)

        self.assertEqual(result, 0)
        self.assertEqual(prompt_yes_no.call_count, 2)
        prompt_key_material.assert_called_once_with(mock.ANY, quiet=True, collect_all_shards=True)
        prompt_quorum_choice.assert_called_once()
        wizard_args = mint_from_plan.call_args.kwargs["args"]
        self.assertIsNone(wizard_args.output_dir)
        self.assertEqual(wizard_args.shard_threshold, 2)
        self.assertEqual(wizard_args.shard_count, 3)
        self.assertIsNone(wizard_args.signing_key_shard_threshold)
        self.assertEqual(mint_from_plan.call_args.kwargs["manifest_signing_seed"], b"s" * 32)
        print_mint_summary.assert_called_once()
        print_completion_actions.assert_called_once()

    @mock.patch("ethernity.cli.flows.mint._print_completion_actions")
    @mock.patch("ethernity.cli.flows.mint.print_mint_summary")
    @mock.patch(
        "ethernity.cli.flows.mint._mint_from_plan",
        return_value=SimpleNamespace(
            doc_id=b"d" * 16,
            output_dir="/tmp/custom-mint",
            shard_paths=(),
            signing_key_shard_paths=(),
            signing_key_source="embedded signing seed",
        ),
    )
    @mock.patch(
        "ethernity.cli.flows.mint.decode_envelope",
        return_value=(SimpleNamespace(signing_seed=b"s" * 32), b"payload"),
    )
    @mock.patch("ethernity.cli.flows.mint.decrypt_bytes", return_value=b"plaintext")
    @mock.patch(
        "ethernity.cli.flows.mint.build_recovery_plan",
        return_value=SimpleNamespace(
            ciphertext=b"ciphertext",
            doc_id=b"d" * 16,
            doc_hash=b"h" * 32,
            passphrase="mint-passphrase",
            auth_payload=SimpleNamespace(sign_pub=b"p" * 32),
        ),
    )
    @mock.patch("ethernity.cli.flows.mint._prompt_key_material")
    @mock.patch(
        "ethernity.cli.flows.mint.prompt_recovery_input_interactive",
        return_value=([], "QR payloads", "qr.txt"),
    )
    @mock.patch("ethernity.cli.flows.mint._prompt_quorum_choice")
    @mock.patch("ethernity.cli.flows.mint.prompt_yes_no", side_effect=[True, False])
    @mock.patch(
        "ethernity.cli.flows.mint.apply_template_design", side_effect=lambda config, design: config
    )
    @mock.patch("ethernity.cli.flows.mint.load_app_config", return_value=SimpleNamespace())
    @mock.patch(
        "ethernity.cli.flows.mint.wizard_stage",
        side_effect=lambda *_args, **_kwargs: contextlib.nullcontext(),
    )
    @mock.patch(
        "ethernity.cli.flows.mint.wizard_flow",
        side_effect=lambda *_args, **_kwargs: contextlib.nullcontext(),
    )
    @mock.patch(
        "ethernity.cli.flows.mint.ui_screen_mode",
        side_effect=lambda **_kwargs: contextlib.nullcontext(),
    )
    @mock.patch("ethernity.cli.flows.mint.sys.stdout.isatty", return_value=True)
    @mock.patch("ethernity.cli.flows.mint.sys.stdin.isatty", return_value=True)
    def test_run_mint_wizard_preserves_explicit_output_directory(
        self,
        _stdin_isatty: mock.MagicMock,
        _stdout_isatty: mock.MagicMock,
        _ui_screen_mode: mock.MagicMock,
        _wizard_flow: mock.MagicMock,
        _wizard_stage: mock.MagicMock,
        _load_app_config: mock.MagicMock,
        _apply_template_design: mock.MagicMock,
        prompt_yes_no: mock.MagicMock,
        prompt_quorum_choice: mock.MagicMock,
        _prompt_recovery_input_interactive: mock.MagicMock,
        prompt_key_material: mock.MagicMock,
        _build_recovery_plan: mock.MagicMock,
        _decrypt_bytes: mock.MagicMock,
        _decode_envelope: mock.MagicMock,
        mint_from_plan: mock.MagicMock,
        print_mint_summary: mock.MagicMock,
        print_completion_actions: mock.MagicMock,
    ) -> None:
        prompt_key_material.return_value = ("passphrase", [], None, [])
        prompt_quorum_choice.return_value = SimpleNamespace(threshold=2, shares=3)

        result = mint_flow.run_mint_wizard(
            MintArgs(output_dir="/tmp/custom-mint", quiet=True),
            debug=False,
            show_header=False,
        )

        self.assertEqual(result, 0)
        self.assertEqual(prompt_yes_no.call_count, 2)
        prompt_key_material.assert_called_once_with(mock.ANY, quiet=True, collect_all_shards=True)
        prompt_quorum_choice.assert_called_once()
        wizard_args = mint_from_plan.call_args.kwargs["args"]
        self.assertEqual(wizard_args.output_dir, "/tmp/custom-mint")
        print_mint_summary.assert_called_once()
        print_completion_actions.assert_called_once()

    @mock.patch("ethernity.cli.flows.mint._print_completion_actions")
    @mock.patch("ethernity.cli.flows.mint.print_mint_summary")
    @mock.patch(
        "ethernity.cli.flows.mint._mint_from_plan",
        return_value=SimpleNamespace(
            doc_id=b"d" * 16,
            output_dir="mint-dd",
            shard_paths=(),
            signing_key_shard_paths=(),
            signing_key_source="embedded signing seed",
        ),
    )
    @mock.patch(
        "ethernity.cli.flows.mint.decode_envelope",
        return_value=(SimpleNamespace(signing_seed=b"s" * 32), b"payload"),
    )
    @mock.patch("ethernity.cli.flows.mint.decrypt_bytes", return_value=b"plaintext")
    @mock.patch(
        "ethernity.cli.flows.mint.build_recovery_plan",
        return_value=SimpleNamespace(
            ciphertext=b"ciphertext",
            doc_id=b"d" * 16,
            doc_hash=b"h" * 32,
            passphrase="mint-passphrase",
            auth_payload=SimpleNamespace(sign_pub=b"p" * 32),
        ),
    )
    @mock.patch("ethernity.cli.flows.mint._prompt_replacement_count", return_value=1)
    @mock.patch("ethernity.cli.flows.mint._prompt_shard_mint_mode", return_value="replacement")
    @mock.patch(
        "ethernity.cli.flows.mint._replacement_payloads_from_frames",
        side_effect=[
            mint_flow._ReplacementShardResolution(
                payloads=(cast(Any, SimpleNamespace(threshold=2, share_count=5, share_index=1)),)
            ),
            mint_flow._ReplacementShardResolution(),
        ],
    )
    @mock.patch("ethernity.cli.flows.mint._missing_replacement_count", return_value=2)
    @mock.patch("ethernity.cli.flows.mint._prompt_key_material")
    @mock.patch(
        "ethernity.cli.flows.mint.prompt_recovery_input_interactive",
        return_value=([], "QR payloads", "qr.txt"),
    )
    @mock.patch("ethernity.cli.flows.mint._prompt_quorum_choice")
    @mock.patch("ethernity.cli.flows.mint.prompt_yes_no", side_effect=[True, False])
    @mock.patch(
        "ethernity.cli.flows.mint.apply_template_design", side_effect=lambda config, design: config
    )
    @mock.patch("ethernity.cli.flows.mint.load_app_config", return_value=SimpleNamespace())
    @mock.patch(
        "ethernity.cli.flows.mint.wizard_stage",
        side_effect=lambda *_args, **_kwargs: contextlib.nullcontext(),
    )
    @mock.patch(
        "ethernity.cli.flows.mint.wizard_flow",
        side_effect=lambda *_args, **_kwargs: contextlib.nullcontext(),
    )
    @mock.patch(
        "ethernity.cli.flows.mint.ui_screen_mode",
        side_effect=lambda **_kwargs: contextlib.nullcontext(),
    )
    @mock.patch("ethernity.cli.flows.mint.sys.stdout.isatty", return_value=True)
    @mock.patch("ethernity.cli.flows.mint.sys.stdin.isatty", return_value=True)
    def test_run_mint_wizard_can_mint_compatible_replacement_passphrase_shard(
        self,
        _stdin_isatty: mock.MagicMock,
        _stdout_isatty: mock.MagicMock,
        _ui_screen_mode: mock.MagicMock,
        _wizard_flow: mock.MagicMock,
        _wizard_stage: mock.MagicMock,
        _load_app_config: mock.MagicMock,
        _apply_template_design: mock.MagicMock,
        prompt_yes_no: mock.MagicMock,
        prompt_quorum_choice: mock.MagicMock,
        _prompt_recovery_input_interactive: mock.MagicMock,
        prompt_key_material: mock.MagicMock,
        _missing_replacement_count: mock.MagicMock,
        _replacement_payloads_from_frames: mock.MagicMock,
        prompt_shard_mint_mode: mock.MagicMock,
        prompt_replacement_count: mock.MagicMock,
        _build_recovery_plan: mock.MagicMock,
        _decrypt_bytes: mock.MagicMock,
        _decode_envelope: mock.MagicMock,
        mint_from_plan: mock.MagicMock,
        print_mint_summary: mock.MagicMock,
        print_completion_actions: mock.MagicMock,
    ) -> None:
        prompt_key_material.return_value = ("passphrase", [], [], [mock.Mock()])

        result = mint_flow.run_mint_wizard(MintArgs(quiet=True), debug=False, show_header=False)

        self.assertEqual(result, 0)
        prompt_key_material.assert_called_once_with(mock.ANY, quiet=True, collect_all_shards=True)
        prompt_shard_mint_mode.assert_called_once()
        prompt_replacement_count.assert_called_once_with("passphrase", maximum=2)
        prompt_quorum_choice.assert_not_called()
        wizard_args = mint_from_plan.call_args.kwargs["args"]
        self.assertEqual(wizard_args.passphrase_replacement_count, 1)
        self.assertIsNone(wizard_args.shard_threshold)
        self.assertFalse(wizard_args.mint_signing_key_shards)
        print_mint_summary.assert_called_once()
        print_completion_actions.assert_called_once()

    @mock.patch("ethernity.cli.flows.mint._print_completion_actions")
    @mock.patch("ethernity.cli.flows.mint.print_mint_summary")
    @mock.patch("ethernity.cli.flows.mint._mint_from_plan")
    @mock.patch(
        "ethernity.cli.flows.mint.decode_envelope",
        return_value=(SimpleNamespace(signing_seed=b"s" * 32), b"payload"),
    )
    @mock.patch("ethernity.cli.flows.mint.decrypt_bytes", return_value=b"plaintext")
    @mock.patch(
        "ethernity.cli.flows.mint.build_recovery_plan",
        return_value=SimpleNamespace(
            ciphertext=b"ciphertext",
            doc_id=b"d" * 16,
            doc_hash=b"h" * 32,
            passphrase="mint-passphrase",
            auth_payload=SimpleNamespace(sign_pub=b"p" * 32),
        ),
    )
    @mock.patch(
        "ethernity.cli.flows.mint._replacement_payloads_from_frames",
        return_value=mint_flow._ReplacementShardResolution(provided_count=1, threshold=2),
    )
    @mock.patch("ethernity.cli.flows.mint._prompt_key_material")
    @mock.patch(
        "ethernity.cli.flows.mint.prompt_recovery_input_interactive",
        return_value=([], "QR payloads", "qr.txt"),
    )
    @mock.patch("ethernity.cli.flows.mint._prompt_quorum_choice")
    @mock.patch("ethernity.cli.flows.mint.prompt_yes_no", side_effect=[True, False])
    @mock.patch(
        "ethernity.cli.flows.mint.apply_template_design", side_effect=lambda config, design: config
    )
    @mock.patch("ethernity.cli.flows.mint.load_app_config", return_value=SimpleNamespace())
    @mock.patch(
        "ethernity.cli.flows.mint.wizard_stage",
        side_effect=lambda *_args, **_kwargs: contextlib.nullcontext(),
    )
    @mock.patch(
        "ethernity.cli.flows.mint.wizard_flow",
        side_effect=lambda *_args, **_kwargs: contextlib.nullcontext(),
    )
    @mock.patch(
        "ethernity.cli.flows.mint.ui_screen_mode",
        side_effect=lambda **_kwargs: contextlib.nullcontext(),
    )
    @mock.patch("ethernity.cli.flows.mint.sys.stdout.isatty", return_value=True)
    @mock.patch("ethernity.cli.flows.mint.sys.stdin.isatty", return_value=True)
    def test_run_mint_wizard_rejects_under_quorum_existing_passphrase_shards(
        self,
        _stdin_isatty: mock.MagicMock,
        _stdout_isatty: mock.MagicMock,
        _ui_screen_mode: mock.MagicMock,
        _wizard_flow: mock.MagicMock,
        _wizard_stage: mock.MagicMock,
        _load_app_config: mock.MagicMock,
        _apply_template_design: mock.MagicMock,
        _prompt_yes_no: mock.MagicMock,
        prompt_quorum_choice: mock.MagicMock,
        _prompt_recovery_input_interactive: mock.MagicMock,
        prompt_key_material: mock.MagicMock,
        _replacement_payloads_from_frames: mock.MagicMock,
        _build_recovery_plan: mock.MagicMock,
        _decrypt_bytes: mock.MagicMock,
        _decode_envelope: mock.MagicMock,
        mint_from_plan: mock.MagicMock,
        print_mint_summary: mock.MagicMock,
        print_completion_actions: mock.MagicMock,
    ) -> None:
        prompt_key_material.return_value = ("passphrase", [], [], [mock.Mock()])

        with self.assertRaisesRegex(
            ValueError,
            r"need at least 2 validated shard\(s\), got 1",
        ):
            mint_flow.run_mint_wizard(MintArgs(quiet=True), debug=False, show_header=False)

        prompt_quorum_choice.assert_not_called()
        mint_from_plan.assert_not_called()
        print_mint_summary.assert_not_called()
        print_completion_actions.assert_not_called()

    @mock.patch("ethernity.cli.flows.mint._print_completion_actions")
    @mock.patch("ethernity.cli.flows.mint.print_mint_summary")
    @mock.patch(
        "ethernity.cli.flows.mint._mint_from_plan",
        return_value=SimpleNamespace(
            doc_id=b"d" * 16,
            output_dir="mint-dd",
            shard_paths=(),
            signing_key_shard_paths=(),
            signing_key_source="embedded signing seed",
        ),
    )
    @mock.patch(
        "ethernity.cli.flows.mint.decode_envelope",
        return_value=(SimpleNamespace(signing_seed=b"s" * 32), b"payload"),
    )
    @mock.patch("ethernity.cli.flows.mint.decrypt_bytes", return_value=b"plaintext")
    @mock.patch(
        "ethernity.cli.flows.mint.build_recovery_plan",
        return_value=SimpleNamespace(
            ciphertext=b"ciphertext",
            doc_id=b"d" * 16,
            doc_hash=b"h" * 32,
            passphrase="mint-passphrase",
            auth_payload=SimpleNamespace(sign_pub=b"p" * 32),
        ),
    )
    @mock.patch("ethernity.cli.flows.mint._prompt_replacement_count")
    @mock.patch("ethernity.cli.flows.mint._prompt_shard_mint_mode", return_value="replacement")
    @mock.patch(
        "ethernity.cli.flows.mint._replacement_payloads_from_frames",
        side_effect=[
            mint_flow._ReplacementShardResolution(
                payloads=(cast(Any, SimpleNamespace(threshold=2, share_count=3, share_index=1)),)
            ),
            mint_flow._ReplacementShardResolution(),
        ],
    )
    @mock.patch("ethernity.cli.flows.mint._missing_replacement_count", return_value=1)
    @mock.patch("ethernity.cli.flows.mint._prompt_key_material")
    @mock.patch(
        "ethernity.cli.flows.mint.prompt_recovery_input_interactive",
        return_value=([], "QR payloads", "qr.txt"),
    )
    @mock.patch("ethernity.cli.flows.mint._prompt_quorum_choice")
    @mock.patch("ethernity.cli.flows.mint.prompt_yes_no", side_effect=[True, False])
    @mock.patch(
        "ethernity.cli.flows.mint.apply_template_design", side_effect=lambda config, design: config
    )
    @mock.patch("ethernity.cli.flows.mint.load_app_config", return_value=SimpleNamespace())
    @mock.patch(
        "ethernity.cli.flows.mint.wizard_stage",
        side_effect=lambda *_args, **_kwargs: contextlib.nullcontext(),
    )
    @mock.patch(
        "ethernity.cli.flows.mint.wizard_flow",
        side_effect=lambda *_args, **_kwargs: contextlib.nullcontext(),
    )
    @mock.patch(
        "ethernity.cli.flows.mint.ui_screen_mode",
        side_effect=lambda **_kwargs: contextlib.nullcontext(),
    )
    @mock.patch("ethernity.cli.flows.mint.sys.stdout.isatty", return_value=True)
    @mock.patch("ethernity.cli.flows.mint.sys.stdin.isatty", return_value=True)
    def test_run_mint_wizard_skips_quantity_prompt_for_single_missing_replacement(
        self,
        _stdin_isatty: mock.MagicMock,
        _stdout_isatty: mock.MagicMock,
        _ui_screen_mode: mock.MagicMock,
        _wizard_flow: mock.MagicMock,
        _wizard_stage: mock.MagicMock,
        _load_app_config: mock.MagicMock,
        _apply_template_design: mock.MagicMock,
        _prompt_yes_no: mock.MagicMock,
        prompt_quorum_choice: mock.MagicMock,
        _prompt_recovery_input_interactive: mock.MagicMock,
        prompt_key_material: mock.MagicMock,
        _missing_replacement_count: mock.MagicMock,
        _replacement_payloads_from_frames: mock.MagicMock,
        prompt_shard_mint_mode: mock.MagicMock,
        prompt_replacement_count: mock.MagicMock,
        _build_recovery_plan: mock.MagicMock,
        _decrypt_bytes: mock.MagicMock,
        _decode_envelope: mock.MagicMock,
        mint_from_plan: mock.MagicMock,
        print_mint_summary: mock.MagicMock,
        print_completion_actions: mock.MagicMock,
    ) -> None:
        prompt_key_material.return_value = ("passphrase", [], [], [mock.Mock()])

        result = mint_flow.run_mint_wizard(MintArgs(quiet=True), debug=False, show_header=False)

        self.assertEqual(result, 0)
        prompt_key_material.assert_called_once_with(mock.ANY, quiet=True, collect_all_shards=True)
        prompt_shard_mint_mode.assert_called_once()
        prompt_replacement_count.assert_not_called()
        prompt_quorum_choice.assert_not_called()
        wizard_args = mint_from_plan.call_args.kwargs["args"]
        self.assertEqual(wizard_args.passphrase_replacement_count, 1)
        self.assertIsNone(wizard_args.shard_threshold)
        print_mint_summary.assert_called_once()
        print_completion_actions.assert_called_once()

    @mock.patch("ethernity.cli.flows.mint._print_completion_actions")
    @mock.patch("ethernity.cli.flows.mint.print_mint_summary")
    @mock.patch(
        "ethernity.cli.flows.mint._mint_from_plan",
        return_value=SimpleNamespace(
            doc_id=b"d" * 16,
            output_dir="mint-dd",
            shard_paths=(),
            signing_key_shard_paths=(),
            signing_key_source="embedded signing seed",
        ),
    )
    @mock.patch(
        "ethernity.cli.flows.mint.decode_envelope",
        return_value=(SimpleNamespace(signing_seed=b"s" * 32), b"payload"),
    )
    @mock.patch("ethernity.cli.flows.mint.decrypt_bytes", return_value=b"plaintext")
    @mock.patch(
        "ethernity.cli.flows.mint.build_recovery_plan",
        return_value=SimpleNamespace(
            ciphertext=b"ciphertext",
            doc_id=b"d" * 16,
            doc_hash=b"h" * 32,
            passphrase="mint-passphrase",
            auth_payload=SimpleNamespace(sign_pub=b"p" * 32),
        ),
    )
    @mock.patch("ethernity.cli.flows.mint._prompt_replacement_count", return_value=1)
    @mock.patch("ethernity.cli.flows.mint._prompt_shard_mint_mode", return_value="replacement")
    @mock.patch("ethernity.cli.flows.mint._missing_replacement_count", return_value=2)
    @mock.patch(
        "ethernity.cli.flows.mint._replacement_payloads_from_frames",
        return_value=mint_flow._ReplacementShardResolution(
            payloads=(cast(Any, SimpleNamespace(threshold=2, share_count=3, share_index=1)),)
        ),
    )
    @mock.patch("ethernity.cli.flows.mint._prompt_shard_inputs")
    @mock.patch("ethernity.cli.flows.mint._prompt_key_material")
    @mock.patch(
        "ethernity.cli.flows.mint.prompt_recovery_input_interactive",
        return_value=([], "QR payloads", "qr.txt"),
    )
    @mock.patch("ethernity.cli.flows.mint._prompt_quorum_choice")
    @mock.patch("ethernity.cli.flows.mint.prompt_yes_no", side_effect=[False, True, True])
    @mock.patch(
        "ethernity.cli.flows.mint.apply_template_design", side_effect=lambda config, design: config
    )
    @mock.patch("ethernity.cli.flows.mint.load_app_config", return_value=SimpleNamespace())
    @mock.patch(
        "ethernity.cli.flows.mint.wizard_stage",
        side_effect=lambda *_args, **_kwargs: contextlib.nullcontext(),
    )
    @mock.patch(
        "ethernity.cli.flows.mint.wizard_flow",
        side_effect=lambda *_args, **_kwargs: contextlib.nullcontext(),
    )
    @mock.patch(
        "ethernity.cli.flows.mint.ui_screen_mode",
        side_effect=lambda **_kwargs: contextlib.nullcontext(),
    )
    @mock.patch("ethernity.cli.flows.mint.sys.stdout.isatty", return_value=True)
    @mock.patch("ethernity.cli.flows.mint.sys.stdin.isatty", return_value=True)
    def test_run_mint_wizard_can_mint_compatible_replacement_signing_key_shard_for_unsealed_backup(
        self,
        _stdin_isatty: mock.MagicMock,
        _stdout_isatty: mock.MagicMock,
        _ui_screen_mode: mock.MagicMock,
        _wizard_flow: mock.MagicMock,
        _wizard_stage: mock.MagicMock,
        _load_app_config: mock.MagicMock,
        _apply_template_design: mock.MagicMock,
        _prompt_yes_no: mock.MagicMock,
        prompt_quorum_choice: mock.MagicMock,
        _prompt_recovery_input_interactive: mock.MagicMock,
        prompt_key_material: mock.MagicMock,
        prompt_shard_inputs: mock.MagicMock,
        _replacement_payloads_from_frames: mock.MagicMock,
        _missing_replacement_count: mock.MagicMock,
        prompt_shard_mint_mode: mock.MagicMock,
        prompt_replacement_count: mock.MagicMock,
        _build_recovery_plan: mock.MagicMock,
        _decrypt_bytes: mock.MagicMock,
        _decode_envelope: mock.MagicMock,
        mint_from_plan: mock.MagicMock,
        print_mint_summary: mock.MagicMock,
        print_completion_actions: mock.MagicMock,
    ) -> None:
        signing_key_frames = [mock.Mock()]
        prompt_key_material.return_value = ("passphrase", [], [], [mock.Mock()])
        prompt_shard_inputs.return_value = ([], [], signing_key_frames)

        result = mint_flow.run_mint_wizard(MintArgs(quiet=True), debug=False, show_header=False)

        self.assertEqual(result, 0)
        prompt_shard_inputs.assert_called_once_with(
            quiet=True,
            key_type=KEY_TYPE_SIGNING_SEED,
            label="Signing-key shard documents",
            stop_at_quorum=False,
        )
        prompt_shard_mint_mode.assert_called_once()
        prompt_replacement_count.assert_called_once_with("signing-key", maximum=2)
        prompt_quorum_choice.assert_not_called()
        wizard_args = mint_from_plan.call_args.kwargs["args"]
        self.assertEqual(wizard_args.signing_key_replacement_count, 1)
        self.assertIsNone(wizard_args.signing_key_shard_threshold)
        self.assertEqual(mint_from_plan.call_args.kwargs["signing_key_frames"], signing_key_frames)
        print_mint_summary.assert_called_once()
        print_completion_actions.assert_called_once()

    @mock.patch("ethernity.cli.flows.mint._print_completion_actions")
    @mock.patch("ethernity.cli.flows.mint.print_mint_summary")
    @mock.patch(
        "ethernity.cli.flows.mint._mint_from_plan",
        return_value=SimpleNamespace(
            doc_id=b"d" * 16,
            output_dir="mint-dd",
            shard_paths=(),
            signing_key_shard_paths=(),
            signing_key_source="embedded signing seed",
        ),
    )
    @mock.patch(
        "ethernity.cli.flows.mint.decode_envelope",
        return_value=(SimpleNamespace(signing_seed=b"s" * 32), b"payload"),
    )
    @mock.patch("ethernity.cli.flows.mint.decrypt_bytes", return_value=b"plaintext")
    @mock.patch(
        "ethernity.cli.flows.mint.build_recovery_plan",
        return_value=SimpleNamespace(
            ciphertext=b"ciphertext",
            doc_id=b"d" * 16,
            doc_hash=b"h" * 32,
            passphrase="mint-passphrase",
            auth_payload=SimpleNamespace(sign_pub=b"p" * 32),
        ),
    )
    @mock.patch(
        "ethernity.cli.flows.mint._replacement_payloads_from_frames",
        return_value=mint_flow._ReplacementShardResolution(),
    )
    @mock.patch("ethernity.cli.flows.mint._prompt_shard_inputs")
    @mock.patch("ethernity.cli.flows.mint._prompt_key_material")
    @mock.patch(
        "ethernity.cli.flows.mint.prompt_recovery_input_interactive",
        return_value=([], "QR payloads", "qr.txt"),
    )
    @mock.patch("ethernity.cli.flows.mint._prompt_quorum_choice")
    @mock.patch("ethernity.cli.flows.mint.prompt_yes_no", side_effect=[False, True, False])
    @mock.patch(
        "ethernity.cli.flows.mint.apply_template_design", side_effect=lambda config, design: config
    )
    @mock.patch("ethernity.cli.flows.mint.load_app_config", return_value=SimpleNamespace())
    @mock.patch(
        "ethernity.cli.flows.mint.wizard_stage",
        side_effect=lambda *_args, **_kwargs: contextlib.nullcontext(),
    )
    @mock.patch(
        "ethernity.cli.flows.mint.wizard_flow",
        side_effect=lambda *_args, **_kwargs: contextlib.nullcontext(),
    )
    @mock.patch(
        "ethernity.cli.flows.mint.ui_screen_mode",
        side_effect=lambda **_kwargs: contextlib.nullcontext(),
    )
    @mock.patch("ethernity.cli.flows.mint.sys.stdout.isatty", return_value=True)
    @mock.patch("ethernity.cli.flows.mint.sys.stdin.isatty", return_value=True)
    def test_run_mint_wizard_can_choose_fresh_signing_key_shards_for_unsealed_backup(
        self,
        _stdin_isatty: mock.MagicMock,
        _stdout_isatty: mock.MagicMock,
        _ui_screen_mode: mock.MagicMock,
        _wizard_flow: mock.MagicMock,
        _wizard_stage: mock.MagicMock,
        _load_app_config: mock.MagicMock,
        _apply_template_design: mock.MagicMock,
        _prompt_yes_no: mock.MagicMock,
        prompt_quorum_choice: mock.MagicMock,
        _prompt_recovery_input_interactive: mock.MagicMock,
        prompt_key_material: mock.MagicMock,
        prompt_shard_inputs: mock.MagicMock,
        _replacement_payloads_from_frames: mock.MagicMock,
        _build_recovery_plan: mock.MagicMock,
        _decrypt_bytes: mock.MagicMock,
        _decode_envelope: mock.MagicMock,
        mint_from_plan: mock.MagicMock,
        print_mint_summary: mock.MagicMock,
        print_completion_actions: mock.MagicMock,
    ) -> None:
        quorum = SimpleNamespace(threshold=2, shares=3)
        prompt_key_material.return_value = ("passphrase", [], [], [mock.Mock()])
        prompt_quorum_choice.return_value = quorum

        result = mint_flow.run_mint_wizard(MintArgs(quiet=True), debug=False, show_header=False)

        self.assertEqual(result, 0)
        prompt_shard_inputs.assert_not_called()
        prompt_quorum_choice.assert_called_once_with(
            title="Signing-key shard quorum",
            help_text=(
                "Choose how many fresh signing-key shard documents to create "
                "and how many are required to recover."
            ),
        )
        wizard_args = mint_from_plan.call_args.kwargs["args"]
        self.assertEqual(wizard_args.signing_key_shard_threshold, quorum.threshold)
        self.assertEqual(wizard_args.signing_key_shard_count, quorum.shares)
        self.assertIsNone(wizard_args.signing_key_replacement_count)
        print_mint_summary.assert_called_once()
        print_completion_actions.assert_called_once()

    @mock.patch("ethernity.cli.flows.mint._print_completion_actions")
    @mock.patch("ethernity.cli.flows.mint.print_mint_summary")
    @mock.patch("ethernity.cli.flows.mint._mint_from_plan")
    @mock.patch(
        "ethernity.cli.flows.mint.decode_envelope",
        return_value=(SimpleNamespace(signing_seed=b"s" * 32), b"payload"),
    )
    @mock.patch("ethernity.cli.flows.mint.decrypt_bytes", return_value=b"plaintext")
    @mock.patch(
        "ethernity.cli.flows.mint.build_recovery_plan",
        return_value=SimpleNamespace(
            ciphertext=b"ciphertext",
            doc_id=b"d" * 16,
            doc_hash=b"h" * 32,
            passphrase="mint-passphrase",
            auth_payload=SimpleNamespace(sign_pub=b"p" * 32),
        ),
    )
    @mock.patch(
        "ethernity.cli.flows.mint._replacement_payloads_from_frames",
        return_value=mint_flow._ReplacementShardResolution(provided_count=1, threshold=2),
    )
    @mock.patch("ethernity.cli.flows.mint._prompt_shard_inputs")
    @mock.patch("ethernity.cli.flows.mint._prompt_key_material")
    @mock.patch(
        "ethernity.cli.flows.mint.prompt_recovery_input_interactive",
        return_value=([], "QR payloads", "qr.txt"),
    )
    @mock.patch("ethernity.cli.flows.mint._prompt_quorum_choice")
    @mock.patch("ethernity.cli.flows.mint.prompt_yes_no", side_effect=[False, True, True])
    @mock.patch(
        "ethernity.cli.flows.mint.apply_template_design", side_effect=lambda config, design: config
    )
    @mock.patch("ethernity.cli.flows.mint.load_app_config", return_value=SimpleNamespace())
    @mock.patch(
        "ethernity.cli.flows.mint.wizard_stage",
        side_effect=lambda *_args, **_kwargs: contextlib.nullcontext(),
    )
    @mock.patch(
        "ethernity.cli.flows.mint.wizard_flow",
        side_effect=lambda *_args, **_kwargs: contextlib.nullcontext(),
    )
    @mock.patch(
        "ethernity.cli.flows.mint.ui_screen_mode",
        side_effect=lambda **_kwargs: contextlib.nullcontext(),
    )
    @mock.patch("ethernity.cli.flows.mint.sys.stdout.isatty", return_value=True)
    @mock.patch("ethernity.cli.flows.mint.sys.stdin.isatty", return_value=True)
    def test_run_mint_wizard_rejects_under_quorum_existing_signing_key_shards_for_unsealed_backup(
        self,
        _stdin_isatty: mock.MagicMock,
        _stdout_isatty: mock.MagicMock,
        _ui_screen_mode: mock.MagicMock,
        _wizard_flow: mock.MagicMock,
        _wizard_stage: mock.MagicMock,
        _load_app_config: mock.MagicMock,
        _apply_template_design: mock.MagicMock,
        _prompt_yes_no: mock.MagicMock,
        prompt_quorum_choice: mock.MagicMock,
        _prompt_recovery_input_interactive: mock.MagicMock,
        prompt_key_material: mock.MagicMock,
        prompt_shard_inputs: mock.MagicMock,
        _replacement_payloads_from_frames: mock.MagicMock,
        _build_recovery_plan: mock.MagicMock,
        _decrypt_bytes: mock.MagicMock,
        _decode_envelope: mock.MagicMock,
        mint_from_plan: mock.MagicMock,
        print_mint_summary: mock.MagicMock,
        print_completion_actions: mock.MagicMock,
    ) -> None:
        prompt_key_material.return_value = ("passphrase", [], [], [mock.Mock()])
        prompt_shard_inputs.return_value = ([], [], [mock.Mock()])

        with self.assertRaisesRegex(
            ValueError,
            r"need at least 2 validated shard\(s\), got 1",
        ):
            mint_flow.run_mint_wizard(MintArgs(quiet=True), debug=False, show_header=False)

        prompt_quorum_choice.assert_not_called()
        mint_from_plan.assert_not_called()
        print_mint_summary.assert_not_called()
        print_completion_actions.assert_not_called()


if __name__ == "__main__":
    unittest.main()
