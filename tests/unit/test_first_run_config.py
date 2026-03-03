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

from ethernity.cli.flows import first_run_config


class TestFirstRunConfig(unittest.TestCase):
    def test_run_first_run_config_wizard_skips_when_not_needed(self) -> None:
        with (
            mock.patch.object(first_run_config, "first_run_onboarding_needed", return_value=False),
            mock.patch.object(first_run_config, "prompt_yes_no") as prompt_yes_no,
        ):
            result = first_run_config.run_first_run_config_wizard(
                config_path=None,
                quiet=True,
                force=False,
            )
        self.assertFalse(result)
        prompt_yes_no.assert_not_called()

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
            mock.patch.object(first_run_config, "prompt_yes_no", return_value=False),
            mock.patch.object(
                first_run_config, "mark_first_run_onboarding_complete"
            ) as mark_complete,
            mock.patch.object(first_run_config, "apply_first_run_defaults") as apply_defaults,
        ):
            result = first_run_config.run_first_run_config_wizard(config_path=None, quiet=False)
        self.assertFalse(result)
        mark_complete.assert_called_once_with()
        apply_defaults.assert_not_called()

    def test_run_first_run_config_wizard_applies_defaults(self) -> None:
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
            mock.patch.object(first_run_config, "prompt_yes_no", side_effect=[True, True]),
            mock.patch.object(first_run_config, "_prompt_design", return_value="forge"),
            mock.patch.object(first_run_config, "_prompt_qr_payload_codec", return_value="base64"),
            mock.patch.object(first_run_config, "_prompt_payload_codec", return_value="gzip"),
            mock.patch.object(
                first_run_config, "resolve_config_path", return_value="/tmp/config.toml"
            ),
            mock.patch.object(first_run_config, "build_review_table", return_value="rows"),
            mock.patch.object(first_run_config, "panel", return_value="panel"),
            mock.patch("ethernity.cli.flows.first_run_config.console.print"),
            mock.patch.object(
                first_run_config, "mark_first_run_onboarding_complete"
            ) as mark_complete,
            mock.patch.object(
                first_run_config,
                "apply_first_run_defaults",
                return_value="/tmp/config.toml",
            ) as apply_defaults,
        ):
            result = first_run_config.run_first_run_config_wizard(config_path=None, quiet=False)
        self.assertTrue(result)
        apply_defaults.assert_called_once_with(
            None,
            design="forge",
            payload_codec="gzip",
            qr_payload_codec="base64",
        )
        mark_complete.assert_called_once_with()

    def test_run_first_run_config_wizard_confirm_no_does_not_apply(self) -> None:
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
            mock.patch.object(first_run_config, "prompt_yes_no", side_effect=[True, False]),
            mock.patch.object(first_run_config, "_prompt_design", return_value="forge"),
            mock.patch.object(first_run_config, "_prompt_qr_payload_codec", return_value="raw"),
            mock.patch.object(first_run_config, "_prompt_payload_codec", return_value="auto"),
            mock.patch.object(
                first_run_config, "resolve_config_path", return_value="/tmp/config.toml"
            ),
            mock.patch.object(first_run_config, "build_review_table", return_value="rows"),
            mock.patch.object(first_run_config, "panel", return_value="panel"),
            mock.patch("ethernity.cli.flows.first_run_config.console.print"),
            mock.patch.object(
                first_run_config, "mark_first_run_onboarding_complete"
            ) as mark_complete,
            mock.patch.object(first_run_config, "apply_first_run_defaults") as apply_defaults,
        ):
            result = first_run_config.run_first_run_config_wizard(config_path=None, quiet=False)
        self.assertFalse(result)
        apply_defaults.assert_not_called()
        mark_complete.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
