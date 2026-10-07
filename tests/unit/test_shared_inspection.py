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

from ethernity.formats.manifest import BackupManifest, ManifestFile
from ethernity.formats.manifest_summary import manifest_summary_payload
from ethernity.workflows.shared import issue_codes
from ethernity.workflows.shared.inspection import (
    blocking_issue,
)


class TestSharedInspection(unittest.TestCase):
    def test_manifest_summary_payload_preserves_schema_and_key_order(self) -> None:
        manifest = BackupManifest(
            created_at=1234.0,
            signing_seed=None,
            files=(
                ManifestFile(
                    path="archive/payload.bin",
                    size=7,
                    sha256=b"x" * 32,
                    mtime=None,
                ),
            ),
            input_origin="directory",
            input_roots=("archive",),
            payload_codec="gzip",
        )

        summary = manifest_summary_payload(manifest)

        self.assertEqual(
            list(summary),
            [
                "input_origin",
                "input_roots",
                "sealed",
                "payload_codec",
                "payload_raw_len",
                "file_count",
            ],
        )
        self.assertEqual(
            summary,
            {
                "input_origin": "directory",
                "input_roots": ["archive"],
                "sealed": True,
                "payload_codec": "gzip",
                "payload_raw_len": 7,
                "file_count": 1,
            },
        )
        self.assertEqual(
            {key: type(value) for key, value in summary.items()},
            {
                "input_origin": str,
                "input_roots": list,
                "sealed": bool,
                "payload_codec": str,
                "payload_raw_len": int,
                "file_count": int,
            },
        )

    def test_blocking_issue_preserves_stable_code_and_details(self) -> None:
        issue = blocking_issue(
            code=issue_codes.AUTH_REQUIRED,
            message="auth is required",
            details={"stage": "inspect"},
        )

        self.assertEqual(issue["code"], issue_codes.AUTH_REQUIRED)
        self.assertEqual(issue["details"], {"stage": "inspect"})

    def test_blocking_issue_preserves_domain_code(self) -> None:
        issue = blocking_issue(code="AD_HOC_FAILURE", message="ad hoc")

        self.assertEqual(issue["code"], "AD_HOC_FAILURE")
