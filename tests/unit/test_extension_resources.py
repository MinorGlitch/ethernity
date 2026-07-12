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

from ethernity.core.bounds import (
    MAX_RECOVERY_CIPHERTEXT_BYTES,
    MAX_RECOVERY_DECODED_CHUNK_BYTES,
    MAX_RECOVERY_DOCUMENTS,
)
from ethernity.extensions.resources import (
    require_chain_resource_limits,
    require_decoded_chunk_resource_limit,
)


class TestExtensionResources(unittest.TestCase):
    def test_chain_transport_limits_accept_exact_boundaries(self) -> None:
        require_chain_resource_limits(
            document_count=MAX_RECOVERY_DOCUMENTS,
            total_ciphertext_bytes=MAX_RECOVERY_CIPHERTEXT_BYTES,
            operation="test chain",
        )

    def test_chain_transport_limits_reject_one_past_each_boundary(self) -> None:
        with self.assertRaisesRegex(ValueError, "Rebuild the latest logical state"):
            require_chain_resource_limits(
                document_count=MAX_RECOVERY_DOCUMENTS + 1,
                total_ciphertext_bytes=0,
                operation="test chain",
            )
        with self.assertRaisesRegex(ValueError, "Rebuild the latest logical state"):
            require_chain_resource_limits(
                document_count=1,
                total_ciphertext_bytes=MAX_RECOVERY_CIPHERTEXT_BYTES + 1,
                operation="test chain",
            )

    def test_decoded_chunk_limit_rejects_one_past_boundary(self) -> None:
        require_decoded_chunk_resource_limit(
            decoded_chunk_bytes=MAX_RECOVERY_DECODED_CHUNK_BYTES,
            operation="test chain",
        )
        with self.assertRaisesRegex(ValueError, "Rebuild the latest logical state"):
            require_decoded_chunk_resource_limit(
                decoded_chunk_bytes=MAX_RECOVERY_DECODED_CHUNK_BYTES + 1,
                operation="test chain",
            )


if __name__ == "__main__":
    unittest.main()
