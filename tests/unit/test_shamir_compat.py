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

from Crypto.Protocol.SecretSharing import Shamir

from ethernity.crypto._shamir_compat import BLOCK_SIZE, interpolate_share_blocks


def _split_secret(secret: bytes, *, threshold: int, shares: int) -> tuple[dict[int, bytes], int]:
    blocks: list[bytes] = []
    for offset in range(0, len(secret), BLOCK_SIZE):
        block = secret[offset : offset + BLOCK_SIZE]
        if len(block) < BLOCK_SIZE:
            block = block.ljust(BLOCK_SIZE, b"\x00")
        blocks.append(block)

    share_map: dict[int, bytearray] = {}
    for block in blocks:
        split = Shamir.split(threshold, shares, block, False)
        for index, share in split:
            share_map.setdefault(index, bytearray()).extend(share)
    return {index: bytes(payload) for index, payload in share_map.items()}, len(blocks)


class TestShamirCompat(unittest.TestCase):
    def test_interpolate_share_blocks_matches_public_shamir_outputs(self) -> None:
        lengths = [1, 15, 16, 17, 31, 32, 33, 64]
        quorum_cases = [(2, 3), (2, 5), (3, 5), (4, 6)]

        for length in lengths:
            secret = bytes((length + offset) % 251 for offset in range(length))
            for threshold, shares in quorum_cases:
                with self.subTest(length=length, threshold=threshold, shares=shares):
                    share_map, block_count = _split_secret(
                        secret, threshold=threshold, shares=shares
                    )
                    for missing_index in range(1, shares + 1):
                        source = [
                            (index, payload)
                            for index, payload in sorted(share_map.items())
                            if index != missing_index
                        ][:threshold]
                        interpolated = interpolate_share_blocks(
                            source,
                            target_index=missing_index,
                            block_count=block_count,
                        )
                        self.assertEqual(interpolated, share_map[missing_index])

    def test_interpolate_share_blocks_rejects_invalid_source_length(self) -> None:
        with self.assertRaisesRegex(ValueError, "share length does not match block count"):
            interpolate_share_blocks([(1, b"short")], target_index=2, block_count=1)

    def test_interpolate_share_blocks_rejects_duplicate_indices(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate share index"):
            interpolate_share_blocks(
                [(1, b"\x00" * BLOCK_SIZE), (1, b"\x01" * BLOCK_SIZE)],
                target_index=2,
                block_count=1,
            )


if __name__ == "__main__":
    unittest.main()
