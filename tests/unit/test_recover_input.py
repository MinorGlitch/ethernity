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

import json
import unittest
from pathlib import Path

from ethernity.cli.flows.recover_input import _PayloadCollectionState, parse_recovery_lines
from ethernity.encoding.framing import DOC_ID_LEN, Frame, FrameType

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE_PATH = _PROJECT_ROOT / "tests" / "fixtures" / "recovery_parse_vectors.json"


class TestRecoverInput(unittest.TestCase):
    def test_recovery_parse_vectors(self) -> None:
        fixture = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
        for case in fixture["recovery_cases"]:
            with self.subTest(case=case["name"]):
                lines = case["input"].splitlines()
                if "expect_error_contains" in case:
                    with self.assertRaisesRegex(ValueError, case["expect_error_contains"]):
                        parse_recovery_lines(
                            lines,
                            allow_unsigned=bool(case["allow_unsigned"]),
                            quiet=True,
                            source=case["name"],
                        )
                    continue

                frames, label = parse_recovery_lines(
                    lines,
                    allow_unsigned=bool(case["allow_unsigned"]),
                    quiet=True,
                    source=case["name"],
                )
                self.assertEqual(label, case["expect_label"])
                frame_types = [FrameType(frame.frame_type).name for frame in frames]
                self.assertEqual(frame_types, case["expect_frame_types"])

    def test_payload_collection_rejects_doc_id_mismatch(self) -> None:
        state = _PayloadCollectionState(allow_unsigned=True, quiet=True)
        first = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x10" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"first",
        )
        second = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x11" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"second",
        )
        self.assertTrue(state.ingest(first))
        self.assertFalse(state.ingest(second))
        self.assertEqual(len(state.frames), 1)

    def test_payload_collection_requires_auth_when_unsigned_disabled(self) -> None:
        state = _PayloadCollectionState(allow_unsigned=False, quiet=True)
        main_frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x20" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"main",
        )
        auth_frame = Frame(
            version=1,
            frame_type=FrameType.AUTH,
            doc_id=b"\x20" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"auth",
        )
        self.assertFalse(state.ingest(main_frame))
        self.assertTrue(state.ingest(auth_frame))
        self.assertEqual(len(state.frames), 2)


if __name__ == "__main__":
    unittest.main()
