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

from hypothesis import given, settings, strategies as st

from ethernity.cli.shared.io.fallback_parser import _is_valid_zbase32_line, filter_fallback_lines
from ethernity.encoding.cbor import dumps_canonical, loads_canonical
from ethernity.encoding.framing import (
    DOC_ID_LEN,
    Frame,
    FrameType,
    decode_frame,
    encode_frame,
)
from ethernity.encoding.qr_payloads import decode_qr_payload, encode_qr_payload

PROPERTY_SETTINGS = settings(deadline=None, max_examples=50)
ZBASE32_CHARS = "ybndrfg8ejkmcpqxot1uwisza345h769"
VALID_FALLBACK_CHARS = ZBASE32_CHARS + ZBASE32_CHARS.upper() + " \t"


def _canonical_cbor_values() -> st.SearchStrategy[object]:
    scalar = st.none() | st.booleans() | st.integers(min_value=-1024, max_value=1024)
    binary = st.binary(max_size=32)
    text = st.text(max_size=32)
    return st.recursive(
        scalar | binary | text,
        lambda children: (
            st.lists(children, max_size=4) | st.dictionaries(text, children, max_size=4)
        ),
        max_leaves=12,
    )


@PROPERTY_SETTINGS
@given(_canonical_cbor_values())
def test_canonical_cbor_roundtrips(value: object) -> None:
    encoded = dumps_canonical(value)
    assert loads_canonical(encoded, label="property") == value


@PROPERTY_SETTINGS
@given(st.binary(max_size=128))
def test_qr_payload_base64_roundtrip(payload: bytes) -> None:
    encoded = encode_qr_payload(payload)
    assert decode_qr_payload(encoded) == payload


@PROPERTY_SETTINGS
@given(
    st.sampled_from([FrameType.MAIN_DOCUMENT, FrameType.AUTH, FrameType.KEY_DOCUMENT]),
    st.binary(min_size=DOC_ID_LEN, max_size=DOC_ID_LEN),
    st.binary(max_size=64),
    st.integers(min_value=1, max_value=8),
)
def test_frame_roundtrip_property(
    frame_type: FrameType,
    doc_id: bytes,
    data: bytes,
    total: int,
) -> None:
    if frame_type is FrameType.MAIN_DOCUMENT:
        index = 0 if total == 1 else 1
    else:
        index = 0
        total = 1
    frame = Frame(
        version=1,
        frame_type=frame_type,
        doc_id=doc_id,
        index=index,
        total=total,
        data=data,
    )
    assert decode_frame(encode_frame(frame)) == frame


@PROPERTY_SETTINGS
@given(st.lists(st.text(alphabet=VALID_FALLBACK_CHARS, min_size=0, max_size=32), max_size=8))
def test_filter_fallback_lines_preserves_valid_lines(lines: list[str]) -> None:
    filtered = filter_fallback_lines(lines)
    expected = [line.strip() for line in lines if _is_valid_zbase32_line(line)]
    assert filtered == expected
    assert all(_is_valid_zbase32_line(line) for line in filtered)


@PROPERTY_SETTINGS
@given(
    st.lists(st.text(alphabet=VALID_FALLBACK_CHARS, min_size=0, max_size=16), max_size=4),
    st.text(alphabet="@#$%!?~", min_size=1, max_size=16),
    st.lists(st.text(alphabet=VALID_FALLBACK_CHARS, min_size=0, max_size=16), max_size=4),
)
def test_filter_fallback_lines_rejects_invalid_non_empty_lines(
    prefix: list[str],
    invalid_line: str,
    suffix: list[str],
) -> None:
    lines = prefix + [invalid_line] + suffix
    try:
        filter_fallback_lines(lines)
    except ValueError as exc:
        assert "outside the z-base-32 alphabet" in str(exc)
    else:
        raise AssertionError("expected invalid non-empty fallback line to be rejected")
