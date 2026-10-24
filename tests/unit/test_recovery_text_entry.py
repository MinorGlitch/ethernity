from __future__ import annotations

import json
from pathlib import Path

import pytest

from ethernity.encoding.fallback_text import parse_fallback_frame, tidy_recovery_text
from ethernity.encoding.framing import DOC_ID_LEN, Frame, FrameType, encode_frame
from ethernity.encoding.zbase32 import encode_zbase32

CASES = json.loads((Path(__file__).parents[1] / "fixtures/recovery_text_entry.json").read_text())


@pytest.mark.parametrize("case", CASES)
def test_cleanup_matches_kit_and_is_idempotent(case: dict[str, str]) -> None:
    cleaned = tidy_recovery_text(case["input"])
    assert cleaned == case["expected"]
    assert tidy_recovery_text(cleaned) == cleaned


def test_numbered_transcription_preserves_frame_and_does_not_hide_bad_labels() -> None:
    frame = Frame(
        version=1,
        frame_type=FrameType.MAIN_DOCUMENT,
        doc_id=b"\x42" * DOC_ID_LEN,
        index=0,
        total=1,
        data=b"paper backup",
    )
    encoded = encode_zbase32(encode_frame(frame))
    lines = [encoded[index : index + 20] for index in range(0, len(encoded), 20)]
    text = "\r\n".join(
        f"{index:02}. \t{line[:4]}\u00a0{line[4:]}  " for index, line in enumerate(lines, 1)
    )
    assert parse_fallback_frame(text.splitlines(), label="main") == frame
    assert parse_fallback_frame(tidy_recovery_text(text).splitlines(), label="main") == frame
    for invalid in ("01. 02. " + encoded, "\u0661. " + encoded, "01 " + encoded):
        with pytest.raises(ValueError):
            parse_fallback_frame(tidy_recovery_text(invalid).splitlines(), label="main")
