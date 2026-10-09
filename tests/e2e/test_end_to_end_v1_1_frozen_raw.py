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

from tests.e2e._frozen_profile_test import FrozenProfileTestCase


class TestStableV1_1FrozenRaw(FrozenProfileTestCase):
    __test__ = True
    FIXTURE_VERSION = "v1_1"
    PROFILE_NAME = "raw"
    QR_PAYLOAD_CODEC = "raw"
    INCLUDE_SHARD_SET_FIELDS = True

    def test_representative_frozen_pdf_backup_recovers(self) -> None:
        self._verify_representative_frozen_pdf_backup_recovers()

    def test_replacement_signing_key_shards_support_followup_replacement(self) -> None:
        self._verify_replacement_signing_key_shards_allow_followup_replacement()

    def test_replacement_signing_key_shards_reject_mixed_sets_at_threshold(self) -> None:
        self._verify_replacement_signing_key_replacement_shards_reject_exact_threshold_mixed_sets()

    def test_replacement_passphrase_shards_reject_mixed_sets_at_threshold(self) -> None:
        self._verify_replacement_shards_reject_exact_threshold_mixed_sets()
