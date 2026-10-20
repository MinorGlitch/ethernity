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

from ethernity.workflows.shared import issue_codes
from ethernity.workflows.shared.inspection import (
    blocking_issue,
)


class TestSharedInspection(unittest.TestCase):
    def test_blocking_issue_preserves_stable_code_and_details(self) -> None:
        issue = blocking_issue(
            code=issue_codes.AUTH_REQUIRED,
            message="auth is required",
            details={"stage": "inspect"},
        )

        self.assertEqual(issue.code, issue_codes.AUTH_REQUIRED)
        self.assertEqual(issue.details, {"stage": "inspect"})

    def test_blocking_issue_preserves_domain_code(self) -> None:
        issue = blocking_issue(code="AD_HOC_FAILURE", message="ad hoc")

        self.assertEqual(issue.code, "AD_HOC_FAILURE")
