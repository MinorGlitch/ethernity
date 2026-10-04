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

from ethernity.encoding.cbor import dumps_deterministic, loads_deterministic


class TestCbor(unittest.TestCase):
    def test_loads_deterministic_wraps_recursion_error(self) -> None:
        with mock.patch(
            "ethernity.encoding.cbor.cbor2.loads",
            side_effect=RecursionError("too deep"),
        ):
            with self.assertRaisesRegex(ValueError, "nesting is too deep"):
                loads_deterministic(b"\x80", label="auth payload")

    def test_loads_deterministic_roundtrip(self) -> None:
        payload = {"version": 1, "value": b"\x01"}
        encoded = dumps_deterministic(payload)
        self.assertEqual(loads_deterministic(encoded, label="payload"), payload)

    def test_loads_deterministic_wraps_decode_errors(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid auth payload CBOR payload"):
            loads_deterministic(b"\x9f\x01", label="auth payload")

    def test_loads_deterministic_wraps_encode_errors(self) -> None:
        with mock.patch(
            "ethernity.encoding.cbor.dumps_deterministic",
            side_effect=cbor2.CBOREncodeError("bad deterministic encoding"),
        ):
            with self.assertRaisesRegex(ValueError, "invalid auth payload CBOR payload"):
                loads_deterministic(dumps_deterministic({"ok": 1}), label="auth payload")


if __name__ == "__main__":
    unittest.main()
