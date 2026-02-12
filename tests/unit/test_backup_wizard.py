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
from unittest import mock

from ethernity.cli.core.types import BackupArgs
from ethernity.cli.flows import backup_wizard
from ethernity.core.models import ShardingConfig, SigningSeedMode
from ethernity.crypto import DEFAULT_PASSPHRASE_WORDS


class TestBackupWizard(unittest.TestCase):
    def test_prompt_passphrase_words_returns_integer_choice(self) -> None:
        with mock.patch.object(backup_wizard, "prompt_choice", return_value="24") as prompt_choice:
            result = backup_wizard.prompt_passphrase_words()
        self.assertEqual(result, 24)
        self.assertEqual(prompt_choice.call_args.kwargs["default"], str(DEFAULT_PASSPHRASE_WORDS))

    def test_prompt_quorum_choice_preset(self) -> None:
        with mock.patch.object(backup_wizard, "prompt_choice", return_value="2of3"):
            config = backup_wizard._prompt_quorum_choice()
        self.assertEqual(config, ShardingConfig(threshold=2, shares=3))

    def test_prompt_quorum_choice_custom(self) -> None:
        with (
            mock.patch.object(backup_wizard, "prompt_choice", return_value="custom"),
            mock.patch.object(backup_wizard, "prompt_int", side_effect=[4, 7]) as prompt_int,
        ):
            config = backup_wizard._prompt_quorum_choice()
        self.assertEqual(config, ShardingConfig(threshold=4, shares=7))
        self.assertEqual(prompt_int.call_count, 2)
        self.assertEqual(prompt_int.call_args_list[1].kwargs["minimum"], 4)

    def test_resolve_passphrase_sharding_incomplete_cli_args_raises(self) -> None:
        args = BackupArgs(shard_threshold=2, shard_count=None)
        with self.assertRaisesRegex(ValueError, "--shard-threshold"):
            backup_wizard.resolve_passphrase_sharding(args=args)

    def test_resolve_passphrase_sharding_cli_accepts_existing(self) -> None:
        args = BackupArgs(shard_threshold=3, shard_count=5)
        with mock.patch.object(backup_wizard, "prompt_yes_no", return_value=True):
            config = backup_wizard.resolve_passphrase_sharding(args=args)
        self.assertEqual(config, ShardingConfig(threshold=3, shares=5))

    def test_resolve_passphrase_sharding_cli_rejects_existing_uses_custom(self) -> None:
        args = BackupArgs(shard_threshold=3, shard_count=5)
        custom = ShardingConfig(threshold=2, shares=4)
        with (
            mock.patch.object(backup_wizard, "prompt_yes_no", return_value=False),
            mock.patch.object(backup_wizard, "_prompt_quorum_choice", return_value=custom),
        ):
            config = backup_wizard.resolve_passphrase_sharding(args=args)
        self.assertEqual(config, custom)

    def test_resolve_passphrase_sharding_interactive_none(self) -> None:
        with mock.patch.object(backup_wizard, "prompt_choice", return_value="none"):
            config = backup_wizard.resolve_passphrase_sharding(args=None)
        self.assertIsNone(config)

    def test_resolve_passphrase_sharding_interactive_shard(self) -> None:
        chosen = ShardingConfig(threshold=2, shares=3)
        with (
            mock.patch.object(backup_wizard, "prompt_choice", return_value="shard"),
            mock.patch.object(backup_wizard, "_prompt_quorum_choice", return_value=chosen),
        ):
            config = backup_wizard.resolve_passphrase_sharding(args=None)
        self.assertEqual(config, chosen)

    def test_resolve_signing_seed_mode_sealed_sharded_warns_and_coerces(self) -> None:
        args = BackupArgs(signing_key_mode="sharded")
        with mock.patch.object(backup_wizard, "_warn") as warn:
            mode = backup_wizard.resolve_signing_seed_mode(args=args, sealed=True, quiet=False)
        self.assertEqual(mode, SigningSeedMode.EMBEDDED)
        warn.assert_called_once()

    def test_resolve_signing_seed_mode_sealed_embedded_keeps_mode(self) -> None:
        args = BackupArgs(signing_key_mode="embedded")
        with mock.patch.object(backup_wizard, "_warn") as warn:
            mode = backup_wizard.resolve_signing_seed_mode(args=args, sealed=True, quiet=True)
        self.assertEqual(mode, SigningSeedMode.EMBEDDED)
        warn.assert_not_called()

    def test_resolve_signing_seed_mode_unsealed_interactive_choice(self) -> None:
        with mock.patch.object(backup_wizard, "prompt_choice", return_value="sharded"):
            mode = backup_wizard.resolve_signing_seed_mode(
                args=BackupArgs(), sealed=False, quiet=True
            )
        self.assertEqual(mode, SigningSeedMode.SHARDED)

    def test_resolve_signing_seed_sharding_non_sharded_returns_none(self) -> None:
        config = backup_wizard.resolve_signing_seed_sharding(
            args=BackupArgs(),
            signing_seed_mode=SigningSeedMode.EMBEDDED,
            passphrase_sharding=ShardingConfig(threshold=2, shares=3),
        )
        self.assertIsNone(config)

    def test_resolve_signing_seed_sharding_incomplete_cli_args_raises(self) -> None:
        args = BackupArgs(signing_key_shard_threshold=2, signing_key_shard_count=None)
        with self.assertRaisesRegex(ValueError, "--signing-key-shard-threshold"):
            backup_wizard.resolve_signing_seed_sharding(
                args=args,
                signing_seed_mode=SigningSeedMode.SHARDED,
                passphrase_sharding=ShardingConfig(threshold=2, shares=3),
            )

    def test_resolve_signing_seed_sharding_cli_quorum_accepted(self) -> None:
        args = BackupArgs(signing_key_shard_threshold=2, signing_key_shard_count=5)
        with mock.patch.object(backup_wizard, "prompt_yes_no", return_value=True):
            config = backup_wizard.resolve_signing_seed_sharding(
                args=args,
                signing_seed_mode=SigningSeedMode.SHARDED,
                passphrase_sharding=ShardingConfig(threshold=3, shares=5),
            )
        self.assertEqual(config, ShardingConfig(threshold=2, shares=5))

    def test_resolve_signing_seed_sharding_same_as_passphrase_returns_none(self) -> None:
        with mock.patch.object(backup_wizard, "prompt_yes_no", return_value=True):
            config = backup_wizard.resolve_signing_seed_sharding(
                args=BackupArgs(),
                signing_seed_mode=SigningSeedMode.SHARDED,
                passphrase_sharding=ShardingConfig(threshold=2, shares=3),
            )
        self.assertIsNone(config)

    def test_resolve_signing_seed_sharding_custom_quorum(self) -> None:
        custom = ShardingConfig(threshold=4, shares=7)
        with (
            mock.patch.object(backup_wizard, "prompt_yes_no", return_value=False),
            mock.patch.object(backup_wizard, "_prompt_quorum_choice", return_value=custom),
        ):
            config = backup_wizard.resolve_signing_seed_sharding(
                args=BackupArgs(),
                signing_seed_mode=SigningSeedMode.SHARDED,
                passphrase_sharding=ShardingConfig(threshold=2, shares=3),
            )
        self.assertEqual(config, custom)


if __name__ == "__main__":
    unittest.main()
