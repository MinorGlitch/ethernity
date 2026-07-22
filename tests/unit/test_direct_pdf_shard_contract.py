import unittest
from dataclasses import replace

from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType, encode_frame
from ethernity.encoding.qr_payloads import QR_PAYLOAD_CODEC_BASE64, encode_qr_payload
from ethernity.render.direct_pdf.shard_contract import validate_single_shard_fallback_contract
from ethernity.render.doc_types import DOC_TYPE_SHARD
from ethernity.render.types import FallbackSection, RenderInputs, RenderLineage


def _inputs(*, qr_payloads: tuple[bytes | str, ...] | None = None) -> RenderInputs:
    frame = Frame(
        version=VERSION,
        frame_type=FrameType.KEY_DOCUMENT,
        doc_id=b"\x91" * DOC_ID_LEN,
        index=0,
        total=1,
        data=b"shard-payload",
    )
    return RenderInputs(
        frames=(frame,),
        output_path="out.pdf",
        context={},
        doc_type=DOC_TYPE_SHARD,
        design_name="forge",
        lineage=RenderLineage(kind="root_backup"),
        qr_payloads=qr_payloads,
        render_qr=True,
        render_fallback=True,
        fallback_sections=(FallbackSection(label="SHARD PAYLOAD", frame=frame),),
    )


class TestDirectPdfShardContract(unittest.TestCase):
    def test_accepts_implicit_raw_and_base64_carriers_for_the_same_frame(self) -> None:
        inputs = _inputs()
        frame_bytes = encode_frame(inputs.frames[0])
        base64_text = encode_qr_payload(frame_bytes, codec=QR_PAYLOAD_CODEC_BASE64)
        assert isinstance(base64_text, str)
        variants = (
            inputs,
            replace(inputs, qr_payloads=(frame_bytes,)),
            replace(inputs, qr_payloads=(base64_text,)),
            replace(inputs, qr_payloads=(base64_text.encode("ascii"),)),
        )

        for variant in variants:
            with self.subTest(qr_payloads=variant.qr_payloads):
                validate_single_shard_fallback_contract(
                    variant,
                    renderer_label="test shard renderer",
                )

    def test_rejects_ambiguous_or_contradictory_sources(self) -> None:
        inputs = _inputs()
        section = (inputs.fallback_sections or ())[0]
        invalid = (
            (
                replace(inputs, fallback_sections=(section, section)),
                "exactly one fallback section",
            ),
            (
                replace(
                    inputs,
                    fallback_sections=(
                        FallbackSection(
                            label=section.label,
                            frame=replace(section.frame, data=b"other"),
                        ),
                    ),
                ),
                "must match its QR frame",
            ),
            (
                replace(
                    inputs,
                    frames=(replace(inputs.frames[0], frame_type=FrameType.MAIN_DOCUMENT),),
                ),
                "KEY_DOCUMENT frame",
            ),
            (replace(inputs, qr_payloads=(b"unrelated",)), "QR payload must encode"),
            (replace(inputs, qr_payloads=("not base64!",)), "QR payload must encode"),
        )

        for variant, message in invalid:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    validate_single_shard_fallback_contract(
                        variant,
                        renderer_label="test shard renderer",
                    )


if __name__ == "__main__":
    unittest.main()
