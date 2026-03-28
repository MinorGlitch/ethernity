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

import cbor2

from ethernity.encoding.cbor import dumps_canonical, loads_canonical


class TestCbor(unittest.TestCase):
    def test_loads_canonical_wraps_recursion_error(self) -> None:
        with mock.patch(
            "ethernity.encoding.cbor.cbor2.loads",
            side_effect=RecursionError("too deep"),
        ):
            with self.assertRaisesRegex(ValueError, "nesting is too deep"):
                loads_canonical(b"\x80", label="auth payload")

    def test_loads_canonical_roundtrip(self) -> None:
        payload = {"version": 1, "value": b"\x01"}
        encoded = dumps_canonical(payload)
        self.assertEqual(loads_canonical(encoded, label="payload"), payload)

    def test_loads_canonical_wraps_decode_errors(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid auth payload CBOR payload"):
            loads_canonical(b"\x9f\x01", label="auth payload")

    def test_loads_canonical_wraps_encode_errors(self) -> None:
        with mock.patch(
            "ethernity.encoding.cbor.dumps_canonical",
            side_effect=cbor2.CBOREncodeError("bad canonical"),
        ):
            with self.assertRaisesRegex(ValueError, "invalid auth payload CBOR payload"):
                loads_canonical(dumps_canonical({"ok": 1}), label="auth payload")


if __name__ == "__main__":
    unittest.main()
