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

import unittest

from ethernity.cli.core.plan import _validate_backup_args
from ethernity.cli.core.types import BackupArgs


class TestBackupArgsValidation(unittest.TestCase):
    def test_qr_chunk_size_zero_rejected(self) -> None:
        args = BackupArgs(qr_chunk_size=0)
        with self.assertRaises(ValueError) as ctx:
            _validate_backup_args(args)
        self.assertIn("qr chunk size", str(ctx.exception).lower())

    def test_qr_chunk_size_negative_rejected(self) -> None:
        args = BackupArgs(qr_chunk_size=-1)
        with self.assertRaises(ValueError) as ctx:
            _validate_backup_args(args)
        self.assertIn("qr chunk size", str(ctx.exception).lower())

    def test_shard_count_over_255_rejected(self) -> None:
        args = BackupArgs(shard_threshold=2, shard_count=256)
        with self.assertRaises(ValueError) as ctx:
            _validate_backup_args(args)
        self.assertIn("shard count", str(ctx.exception).lower())

    def test_signing_key_shard_count_over_255_rejected(self) -> None:
        args = BackupArgs(
            shard_threshold=2,
            shard_count=3,
            signing_key_mode="sharded",
            signing_key_shard_threshold=2,
            signing_key_shard_count=256,
        )
        with self.assertRaises(ValueError) as ctx:
            _validate_backup_args(args)
        self.assertIn("signing key shard count", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
