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

from ethernity.cli.shared import api_codes
from ethernity.cli.shared.inspection import blocking_issue, inspect_result_payload


class TestSharedInspection(unittest.TestCase):
    def test_blocking_issue_preserves_stable_code_and_details(self) -> None:
        issue = blocking_issue(
            code=api_codes.AUTH_REQUIRED,
            message="auth is required",
            details={"stage": "inspect"},
        )

        self.assertEqual(issue["code"], api_codes.AUTH_REQUIRED)
        self.assertEqual(issue["details"], {"stage": "inspect"})

    def test_blocking_issue_maps_unknown_code_to_invalid_input(self) -> None:
        issue = blocking_issue(code="AD_HOC_FAILURE", message="ad hoc")

        self.assertEqual(issue["code"], api_codes.INVALID_INPUT)

    def test_inspect_result_payload_normalizes_common_shape(self) -> None:
        payload = inspect_result_payload(
            command="recover",
            source_summary=None,
            frame_counts={"main": 1},
            unlock={"satisfied": False},
            blocking_issues=[{"code": api_codes.PASSPHRASE_REQUIRED, "message": "missing"}],
            warnings=(),
            doc_id="abcd",
        )

        self.assertEqual(payload["operation"], "inspect")
        self.assertEqual(payload["command"], "recover")
        self.assertEqual(payload["source_summary"], None)
        self.assertEqual(payload["frame_counts"], {"main": 1})
        self.assertEqual(payload["unlock"], {"satisfied": False})
        self.assertEqual(payload["doc_id"], "abcd")
        self.assertEqual(payload["blocking_issues"][0]["details"], {})
