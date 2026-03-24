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
from unittest import mock

from ethernity.cli.features.recover.planning import _inspect_auth_payload
from ethernity.encoding.framing import DOC_ID_LEN, Frame, FrameType


class TestInspectAuthPayload(unittest.TestCase):
    @staticmethod
    def _auth_frame(*, doc_id: bytes) -> Frame:
        return Frame(
            version=1,
            frame_type=FrameType.AUTH,
            doc_id=doc_id,
            index=0,
            total=1,
            data=b"auth",
        )

    def test_doc_id_mismatch_is_ignored_in_allow_unsigned_mode(self) -> None:
        frame = self._auth_frame(doc_id=b"\x11" * DOC_ID_LEN)
        with mock.patch("ethernity.cli.features.recover.planning._warn") as warn_mock:
            payload, status, blocking_issues = _inspect_auth_payload(
                [frame],
                doc_id=b"\x12" * DOC_ID_LEN,
                doc_hash=b"\x20" * 32,
                allow_unsigned=True,
                require_auth=False,
                quiet=True,
            )
        self.assertIsNone(payload)
        self.assertEqual(status, "ignored")
        self.assertEqual(blocking_issues, ())
        warn_mock.assert_called_once()

    def test_doc_id_mismatch_is_blocking_in_strict_mode(self) -> None:
        frame = self._auth_frame(doc_id=b"\x11" * DOC_ID_LEN)
        payload, status, blocking_issues = _inspect_auth_payload(
            [frame],
            doc_id=b"\x12" * DOC_ID_LEN,
            doc_hash=b"\x20" * 32,
            allow_unsigned=False,
            require_auth=True,
            quiet=True,
        )
        self.assertIsNone(payload)
        self.assertEqual(status, "invalid")
        self.assertEqual(len(blocking_issues), 1)
        self.assertEqual(blocking_issues[0]["code"], "AUTH_PAYLOAD_DOC_ID_MISMATCH")


if __name__ == "__main__":
    unittest.main()
