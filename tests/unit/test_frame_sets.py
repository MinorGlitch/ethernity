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

from ethernity.encoding.frame_sets import (
    deduplicate_auth_frames,
    deduplicate_frame_slots,
    deduplicate_identical_frames,
    split_main_and_auth_frames,
)
from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType


class TestFrameSets(unittest.TestCase):
    @staticmethod
    def _frame(
        *,
        frame_type: FrameType = FrameType.MAIN_DOCUMENT,
        doc_id: bytes | None = None,
        index: int = 0,
        total: int = 1,
        data: bytes = b"payload",
    ) -> Frame:
        return Frame(
            version=VERSION,
            frame_type=frame_type,
            doc_id=doc_id or (b"\x11" * DOC_ID_LEN),
            index=index,
            total=total,
            data=data,
        )

    def test_frame_slot_deduplication_preserves_first_occurrence_order(self) -> None:
        first = self._frame()
        second = self._frame(doc_id=b"\x22" * DOC_ID_LEN)

        self.assertEqual(deduplicate_frame_slots([first, second, first]), [first, second])

    def test_frame_slot_deduplication_rejects_data_and_total_conflicts(self) -> None:
        first = self._frame(data=b"A")
        conflicts = (
            self._frame(data=b"B"),
            self._frame(data=b"A", total=2),
        )

        for conflict in conflicts:
            with self.subTest(conflict=conflict):
                with self.assertRaisesRegex(ValueError, "conflicting duplicate"):
                    deduplicate_frame_slots([first, conflict])

    def test_identical_deduplication_keeps_nonidentical_slot_conflicts(self) -> None:
        first = self._frame(data=b"A")
        data_conflict = self._frame(data=b"B")
        total_conflict = self._frame(data=b"A", total=2)

        with self.assertRaisesRegex(ValueError, "conflicting duplicate"):
            deduplicate_frame_slots([first, data_conflict])
        self.assertEqual(
            deduplicate_identical_frames(
                [first, first, data_conflict, data_conflict, total_conflict]
            ),
            [first, data_conflict, total_conflict],
        )

    def test_auth_deduplication_handles_empty_and_identical_auth_frames(self) -> None:
        auth = self._frame(
            frame_type=FrameType.AUTH,
            doc_id=b"\x36" * DOC_ID_LEN,
            data=b"auth",
        )

        self.assertEqual(deduplicate_auth_frames([]), [])
        self.assertEqual(deduplicate_auth_frames([auth, auth]), [auth])

    def test_auth_deduplication_rejects_non_auth_frames(self) -> None:
        with self.assertRaisesRegex(ValueError, "AUTH type"):
            deduplicate_auth_frames([self._frame()])

    def test_split_main_and_auth_frames_preserves_type_order(self) -> None:
        main_first = self._frame(index=0, total=2, data=b"first")
        auth = self._frame(frame_type=FrameType.AUTH, data=b"auth")
        main_second = self._frame(index=1, total=2, data=b"second")

        self.assertEqual(
            split_main_and_auth_frames([main_first, auth, main_second]),
            ([main_first, main_second], [auth]),
        )

    def test_split_main_and_auth_frames_requires_main(self) -> None:
        auth = self._frame(frame_type=FrameType.AUTH)
        with self.assertRaisesRegex(ValueError, "no main document payloads"):
            split_main_and_auth_frames([auth])

    def test_split_main_and_auth_frames_rejects_unexpected_type(self) -> None:
        main = self._frame()
        shard = self._frame(frame_type=FrameType.KEY_DOCUMENT)
        with self.assertRaisesRegex(ValueError, "unexpected frame type"):
            split_main_and_auth_frames([main, shard])
