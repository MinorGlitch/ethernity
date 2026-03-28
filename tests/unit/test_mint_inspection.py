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

import unittest
from types import SimpleNamespace
from unittest import mock

from ethernity.cli.features.mint.workflow import inspect_mint_inputs
from ethernity.cli.shared.types import MintArgs


class TestMintInspection(unittest.TestCase):
    def test_inspect_mint_inputs_deduplicates_auth_required_blockers(self) -> None:
        args = MintArgs(payloads_file="main.txt", quiet=True)
        state = SimpleNamespace(
            frames=(),
            extra_auth_frames=(),
            shard_frames=(),
            shard_fallback_files=(),
            shard_payloads_file=(),
            shard_scan=(),
            signing_key_frames=(),
            input_label="QR payloads",
            input_detail="main.txt",
        )
        auth_required = {
            "code": "AUTH_REQUIRED",
            "message": "minting requires an authenticated backup input with an AUTH payload",
            "details": {},
        }
        recovery = SimpleNamespace(
            auth_payload=None,
            blocking_issues=(),
            unlock=SimpleNamespace(satisfied=False, resolved_passphrase=None),
            ciphertext=b"",
            doc_id=b"\x01" * 8,
            doc_hash=b"\x02" * 32,
        )

        with (
            mock.patch(
                "ethernity.cli.features.mint.workflow._load_mint_input_state",
                return_value=state,
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow._recovery_shard_inputs_for_plan",
                return_value=([], [], []),
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow.inspect_recovery_inputs",
                return_value=recovery,
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow._inspect_mint_signing_key_state",
                return_value=(0, None, False, "signing-key shards", [auth_required]),
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow._inspect_mint_replacement_blockers",
                return_value=[],
            ),
            mock.patch(
                "ethernity.cli.features.mint.workflow._inspect_mint_capabilities",
                return_value={
                    "can_mint_passphrase_shards": False,
                    "can_mint_signing_key_shards": False,
                },
            ),
        ):
            inspection = inspect_mint_inputs(args)

        auth_required_issues = [
            issue for issue in inspection.blocking_issues if issue.get("code") == "AUTH_REQUIRED"
        ]
        self.assertEqual(len(auth_required_issues), 1)


if __name__ == "__main__":
    unittest.main()
