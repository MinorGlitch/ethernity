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
from ethernity.cli.shared.inspection import (
    blocking_issue,
    inspect_result_payload,
    manifest_summary_payload,
)
from ethernity.formats.envelope_types import EnvelopeManifest, ManifestFile


class TestSharedInspection(unittest.TestCase):
    def test_manifest_summary_payload_preserves_contract_and_key_order(self) -> None:
        manifest = EnvelopeManifest(
            format_version=1,
            created_at=1234.0,
            sealed=True,
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
            payload_raw_len=7,
        )

        summary = manifest_summary_payload(manifest)

        self.assertEqual(
            list(summary),
            [
                "format_version",
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
                "format_version": 1,
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
                "format_version": int,
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
