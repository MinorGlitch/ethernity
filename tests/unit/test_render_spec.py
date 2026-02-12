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

from ethernity.render.spec import document_spec


class TestRenderSpec(unittest.TestCase):
    def test_document_spec_rejects_unknown_doc_type(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported doc type"):
            document_spec("unknown", "A4", {})


if __name__ == "__main__":
    unittest.main()
