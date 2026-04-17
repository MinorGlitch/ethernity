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
from unittest import mock

from ethernity.cli.features.config import onboarding as first_run_config


class TestFirstRunConfig(unittest.TestCase):
    def test_run_first_run_config_wizard_skips_when_not_needed(self) -> None:
        with (
            mock.patch.object(first_run_config, "first_run_onboarding_needed", return_value=False),
            mock.patch.object(first_run_config, "prompt_choice") as prompt_choice,
        ):
            result = first_run_config.run_first_run_config_wizard(
                config_path=None,
                quiet=True,
                force=False,
            )
        self.assertFalse(result.applied_defaults)
        self.assertIsNone(result.launch_action)
        prompt_choice.assert_not_called()

    def test_run_first_run_config_wizard_skip_marks_complete(self) -> None:
        with (
            mock.patch.object(first_run_config, "first_run_onboarding_needed", return_value=True),
            mock.patch.object(
                first_run_config,
                "wizard_flow",
                return_value=contextlib.nullcontext(),
            ),
            mock.patch.object(
                first_run_config,
                "wizard_stage",
                return_value=contextlib.nullcontext(),
            ),
            mock.patch.object(first_run_config, "clear_screen") as clear_screen,
            mock.patch.object(first_run_config, "render_home_banner") as render_home_banner,
            mock.patch.object(first_run_config, "prompt_choice", return_value="skip"),
            mock.patch.object(
                first_run_config, "mark_first_run_onboarding_complete"
            ) as mark_complete,
            mock.patch.object(first_run_config, "apply_first_run_defaults") as apply_defaults,
        ):
            result = first_run_config.run_first_run_config_wizard(config_path=None, quiet=False)
        self.assertFalse(result.applied_defaults)
        self.assertIsNone(result.launch_action)
        clear_screen.assert_called_once_with()
        render_home_banner.assert_called_once_with()
        mark_complete.assert_called_once_with()
        apply_defaults.assert_not_called()

    def test_run_first_run_config_wizard_backup_launches_directly(self) -> None:
        with (
            mock.patch.object(first_run_config, "first_run_onboarding_needed", return_value=True),
            mock.patch.object(
                first_run_config,
                "wizard_flow",
                return_value=contextlib.nullcontext(),
            ),
            mock.patch.object(
                first_run_config,
                "wizard_stage",
                return_value=contextlib.nullcontext(),
            ),
            mock.patch.object(first_run_config, "clear_screen") as clear_screen,
            mock.patch.object(first_run_config, "render_home_banner") as render_home_banner,
            mock.patch.object(first_run_config, "prompt_choice", return_value="backup"),
            mock.patch.object(
                first_run_config, "mark_first_run_onboarding_complete"
            ) as mark_complete,
            mock.patch.object(first_run_config, "apply_first_run_defaults") as apply_defaults,
        ):
            result = first_run_config.run_first_run_config_wizard(config_path=None, quiet=False)
        self.assertFalse(result.applied_defaults)
        self.assertEqual(result.launch_action, "backup")
        clear_screen.assert_called_once_with()
        render_home_banner.assert_called_once_with()
        mark_complete.assert_called_once_with()
        apply_defaults.assert_not_called()

    def test_run_first_run_config_wizard_applies_defaults(self) -> None:
        with contextlib.ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(
                    first_run_config,
                    "first_run_onboarding_needed",
                    return_value=True,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    first_run_config,
                    "wizard_flow",
                    return_value=contextlib.nullcontext(),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    first_run_config,
                    "wizard_stage",
                    return_value=contextlib.nullcontext(),
                )
            )
            clear_screen = stack.enter_context(mock.patch.object(first_run_config, "clear_screen"))
            render_home_banner = stack.enter_context(
                mock.patch.object(first_run_config, "render_home_banner")
            )
            stack.enter_context(
                mock.patch.object(first_run_config, "prompt_choice", return_value="configure")
            )
            stack.enter_context(
                mock.patch.object(
                    first_run_config,
                    "prompt_yes_no",
                    side_effect=[True, True],
                )
            )
            stack.enter_context(
                mock.patch.object(first_run_config, "_prompt_design", return_value="forge")
            )
            stack.enter_context(
                mock.patch.object(
                    first_run_config,
                    "_prompt_qr_payload_codec",
                    return_value="base64",
                )
            )
            stack.enter_context(
                mock.patch.object(first_run_config, "_prompt_qr_error_correction", return_value="Q")
            )
            stack.enter_context(
                mock.patch.object(first_run_config, "_prompt_payload_codec", return_value="gzip")
            )
            stack.enter_context(
                mock.patch.object(first_run_config, "_prompt_page_size", return_value="LETTER")
            )
            stack.enter_context(
                mock.patch.object(
                    first_run_config,
                    "_prompt_backup_output_dir",
                    return_value="/tmp/backups",
                )
            )
            stack.enter_context(
                mock.patch.object(first_run_config, "_prompt_qr_chunk_size", return_value=384)
            )
            stack.enter_context(
                mock.patch.object(
                    first_run_config,
                    "_prompt_sharding_defaults",
                    return_value=(2, 3, "sharded"),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    first_run_config,
                    "resolve_config_path",
                    return_value="/tmp/config.toml",
                )
            )
            stack.enter_context(
                mock.patch.object(first_run_config, "build_review_table", return_value="rows")
            )
            stack.enter_context(mock.patch.object(first_run_config, "panel", return_value="panel"))
            stack.enter_context(
                mock.patch("ethernity.cli.features.config.onboarding.console.print")
            )
            mark_complete = stack.enter_context(
                mock.patch.object(first_run_config, "mark_first_run_onboarding_complete")
            )
            apply_defaults = stack.enter_context(
                mock.patch.object(
                    first_run_config,
                    "apply_first_run_defaults",
                    return_value="/tmp/config.toml",
                )
            )
            result = first_run_config.run_first_run_config_wizard(config_path=None, quiet=False)
        self.assertTrue(result.applied_defaults)
        self.assertIsNone(result.launch_action)
        clear_screen.assert_called_once_with()
        render_home_banner.assert_called_once_with()
        apply_defaults.assert_called_once_with(
            None,
            design="forge",
            payload_codec="gzip",
            qr_payload_codec="base64",
            qr_error_correction="Q",
            page_size="LETTER",
            backup_output_dir="/tmp/backups",
            qr_chunk_size=384,
            shard_threshold=2,
            shard_count=3,
            signing_key_mode="sharded",
        )
        mark_complete.assert_called_once()
        self.assertEqual(
            mark_complete.call_args.kwargs["configured_fields"],
            {
                "template_design",
                "page_size",
                "backup_output_dir",
                "sharding",
                "payload_codec",
                "qr_payload_codec",
                "qr_error_correction",
                "qr_chunk_size",
            },
        )

    def test_run_first_run_config_wizard_keeps_recommended_advanced_defaults(self) -> None:
        with contextlib.ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(
                    first_run_config,
                    "first_run_onboarding_needed",
                    return_value=True,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    first_run_config,
                    "wizard_flow",
                    return_value=contextlib.nullcontext(),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    first_run_config,
                    "wizard_stage",
                    return_value=contextlib.nullcontext(),
                )
            )
            clear_screen = stack.enter_context(mock.patch.object(first_run_config, "clear_screen"))
            render_home_banner = stack.enter_context(
                mock.patch.object(first_run_config, "render_home_banner")
            )
            stack.enter_context(
                mock.patch.object(first_run_config, "prompt_choice", return_value="configure")
            )
            stack.enter_context(
                mock.patch.object(
                    first_run_config,
                    "prompt_yes_no",
                    side_effect=[False, True],
                )
            )
            stack.enter_context(
                mock.patch.object(first_run_config, "_prompt_design", return_value="sentinel")
            )
            advanced_qr_payload = stack.enter_context(
                mock.patch.object(
                    first_run_config, "_prompt_qr_payload_codec", return_value="base64"
                )
            )
            advanced_qr_error = stack.enter_context(
                mock.patch.object(first_run_config, "_prompt_qr_error_correction", return_value="Q")
            )
            advanced_payload = stack.enter_context(
                mock.patch.object(first_run_config, "_prompt_payload_codec", return_value="gzip")
            )
            stack.enter_context(
                mock.patch.object(first_run_config, "_prompt_page_size", return_value="A4")
            )
            stack.enter_context(
                mock.patch.object(first_run_config, "_prompt_backup_output_dir", return_value=None)
            )
            advanced_qr_chunk = stack.enter_context(
                mock.patch.object(first_run_config, "_prompt_qr_chunk_size", return_value=384)
            )
            stack.enter_context(
                mock.patch.object(
                    first_run_config,
                    "_prompt_sharding_defaults",
                    return_value=(2, 3, "embedded"),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    first_run_config,
                    "resolve_config_path",
                    return_value="/tmp/config.toml",
                )
            )
            stack.enter_context(
                mock.patch.object(first_run_config, "build_review_table", return_value="rows")
            )
            stack.enter_context(mock.patch.object(first_run_config, "panel", return_value="panel"))
            stack.enter_context(
                mock.patch("ethernity.cli.features.config.onboarding.console.print")
            )
            mark_complete = stack.enter_context(
                mock.patch.object(first_run_config, "mark_first_run_onboarding_complete")
            )
            apply_defaults = stack.enter_context(
                mock.patch.object(
                    first_run_config,
                    "apply_first_run_defaults",
                    return_value="/tmp/config.toml",
                )
            )

            result = first_run_config.run_first_run_config_wizard(config_path=None, quiet=False)

        self.assertTrue(result.applied_defaults)
        self.assertIsNone(result.launch_action)
        clear_screen.assert_called_once_with()
        render_home_banner.assert_called_once_with()
        advanced_qr_payload.assert_not_called()
        advanced_qr_error.assert_not_called()
        advanced_payload.assert_not_called()
        advanced_qr_chunk.assert_not_called()
        apply_defaults.assert_called_once_with(
            None,
            design="sentinel",
            payload_codec="auto",
            qr_payload_codec="raw",
            qr_error_correction="M",
            page_size="A4",
            backup_output_dir=None,
            qr_chunk_size=768,
            shard_threshold=2,
            shard_count=3,
            signing_key_mode="embedded",
        )
        self.assertEqual(
            mark_complete.call_args.kwargs["configured_fields"],
            {
                "template_design",
                "page_size",
                "backup_output_dir",
                "sharding",
            },
        )

    def test_run_first_run_config_wizard_confirm_no_does_not_apply(self) -> None:
        with contextlib.ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(
                    first_run_config,
                    "first_run_onboarding_needed",
                    return_value=True,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    first_run_config,
                    "wizard_flow",
                    return_value=contextlib.nullcontext(),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    first_run_config,
                    "wizard_stage",
                    return_value=contextlib.nullcontext(),
                )
            )
            clear_screen = stack.enter_context(mock.patch.object(first_run_config, "clear_screen"))
            render_home_banner = stack.enter_context(
                mock.patch.object(first_run_config, "render_home_banner")
            )
            stack.enter_context(
                mock.patch.object(first_run_config, "prompt_choice", return_value="configure")
            )
            stack.enter_context(
                mock.patch.object(
                    first_run_config,
                    "prompt_yes_no",
                    side_effect=[False, False],
                )
            )
            stack.enter_context(
                mock.patch.object(first_run_config, "_prompt_design", return_value="forge")
            )
            stack.enter_context(
                mock.patch.object(first_run_config, "_prompt_qr_payload_codec", return_value="raw")
            )
            stack.enter_context(
                mock.patch.object(first_run_config, "_prompt_qr_error_correction", return_value="M")
            )
            stack.enter_context(
                mock.patch.object(first_run_config, "_prompt_payload_codec", return_value="auto")
            )
            stack.enter_context(
                mock.patch.object(first_run_config, "_prompt_page_size", return_value="A4")
            )
            stack.enter_context(
                mock.patch.object(first_run_config, "_prompt_backup_output_dir", return_value=None)
            )
            stack.enter_context(
                mock.patch.object(first_run_config, "_prompt_qr_chunk_size", return_value=512)
            )
            stack.enter_context(
                mock.patch.object(
                    first_run_config,
                    "_prompt_sharding_defaults",
                    return_value=(None, None, None),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    first_run_config,
                    "resolve_config_path",
                    return_value="/tmp/config.toml",
                )
            )
            stack.enter_context(
                mock.patch.object(first_run_config, "build_review_table", return_value="rows")
            )
            stack.enter_context(mock.patch.object(first_run_config, "panel", return_value="panel"))
            stack.enter_context(
                mock.patch("ethernity.cli.features.config.onboarding.console.print")
            )
            mark_complete = stack.enter_context(
                mock.patch.object(first_run_config, "mark_first_run_onboarding_complete")
            )
            apply_defaults = stack.enter_context(
                mock.patch.object(first_run_config, "apply_first_run_defaults")
            )
            result = first_run_config.run_first_run_config_wizard(config_path=None, quiet=False)
        self.assertFalse(result.applied_defaults)
        self.assertIsNone(result.launch_action)
        clear_screen.assert_called_once_with()
        render_home_banner.assert_called_once_with()
        apply_defaults.assert_not_called()
        mark_complete.assert_called_once_with()

    def test_run_first_run_config_wizard_quiet_skips_screen_clear_and_banner(self) -> None:
        with (
            mock.patch.object(first_run_config, "first_run_onboarding_needed", return_value=True),
            mock.patch.object(
                first_run_config,
                "wizard_flow",
                return_value=contextlib.nullcontext(),
            ),
            mock.patch.object(
                first_run_config,
                "wizard_stage",
                return_value=contextlib.nullcontext(),
            ),
            mock.patch.object(first_run_config, "clear_screen") as clear_screen,
            mock.patch.object(first_run_config, "render_home_banner") as render_home_banner,
            mock.patch.object(first_run_config, "prompt_choice", return_value="skip"),
            mock.patch.object(first_run_config, "mark_first_run_onboarding_complete"),
            mock.patch.object(first_run_config, "apply_first_run_defaults"),
        ):
            first_run_config.run_first_run_config_wizard(config_path=None, quiet=True)
        clear_screen.assert_not_called()
        render_home_banner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
