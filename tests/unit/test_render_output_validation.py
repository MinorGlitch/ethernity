"""Regressions that validate the emitted PDF independently of renderer layouts."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from unittest import mock

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject
from scripts import render_visual_baselines as baselines

from ethernity.crypto import sharding
from ethernity.crypto.signing import generate_signing_keypair
from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType, encode_frame
from ethernity.encoding.qr_payloads import encode_qr_payload
from ethernity.qr.codec import QrConfig, qr_bytes
from ethernity.render import render_frames_to_pdf
from ethernity.render.checks import (
    RenderValidationError,
    build_rendered_document_summary,
    extract_pdf_text,
)
from ethernity.render.direct_pdf import document_inputs
from ethernity.render.direct_pdf.surface import FpdfSurface
from ethernity.render.recovery_meta import build_recovery_meta
from ethernity.render.types import DocumentOrigin, FallbackSection, RenderInputs
from ethernity.render.validation import validate_rendered_pdf_document

_DESIGNS = ("archive", "forge", "ledger", "maritime", "sentinel")


def _inputs(tmp_path: Path, design: str, role: str) -> RenderInputs:
    case = baselines.VisualBaselineCase(design, role, "A4")
    return baselines.build_sample_inputs(case, tmp_path / f"{design}-{role}.pdf")


def _validate(inputs: RenderInputs, result: object) -> None:
    validate_rendered_pdf_document(inputs=inputs, result=result, document_label="test document")


def _rewrite_page_paint(inputs: RenderInputs, *, prefix: bytes = b"", cover: bool = False) -> None:
    reader = PdfReader(inputs.output_path)
    writer = PdfWriter()
    for page in reader.pages:
        content = prefix + page.get_contents().get_data()
        if cover:
            content += (
                f"\nq 1 g 0 0 {float(page.mediabox.width)} {float(page.mediabox.height)} re f Q\n"
            ).encode("ascii")
        stream = DecodedStreamObject()
        stream.set_data(content)
        page[NameObject("/Contents")] = stream
        writer.add_page(page)
    writer.write(inputs.output_path)


@pytest.mark.parametrize("design", _DESIGNS)
def test_covered_qrs_with_original_layouts_and_resources_are_rejected(
    tmp_path: Path, design: str
) -> None:
    inputs = _inputs(tmp_path, design, "main")
    result = render_frames_to_pdf(inputs)
    _rewrite_page_paint(inputs, cover=True)
    with pytest.raises(RenderValidationError, match="no usable QR"):
        _validate(inputs, result)


@pytest.mark.parametrize("design", _DESIGNS)
@pytest.mark.parametrize("dark", ((0, 0, 0, 3), "#fefefe"))
def test_faint_composed_qrs_are_rejected(tmp_path: Path, design: str, dark: object) -> None:
    inputs = _inputs(tmp_path, design, "main")
    inputs = replace(
        inputs,
        frames=(replace(inputs.frames[0], index=0, total=1),),
        qr_config=QrConfig(dark=dark, light="white"),
    )
    result = render_frames_to_pdf(inputs)
    with pytest.raises(RenderValidationError, match="no usable QR"):
        _validate(inputs, result)


@pytest.mark.parametrize("design", _DESIGNS)
@pytest.mark.parametrize("invisible", (True, False), ids=("invisible-mode", "covered-page"))
def test_invisible_recovery_text_is_rejected(tmp_path: Path, design: str, invisible: bool) -> None:
    inputs = _inputs(tmp_path, design, "recovery")
    result = render_frames_to_pdf(inputs)
    _rewrite_page_paint(inputs, prefix=b"3 Tr\n" if invisible else b"", cover=not invisible)
    with pytest.raises(RenderValidationError, match="invisible|unreadable"):
        _validate(inputs, result)


@pytest.mark.parametrize("design", _DESIGNS)
def test_prose_and_headings_cannot_supply_the_printed_passphrase(
    tmp_path: Path, design: str
) -> None:
    secret = "RECOVERY DOCUMENT" if design == "sentinel" else "Keep it separate"
    inputs = replace(
        _inputs(tmp_path, design, "recovery"),
        recovery_meta=build_recovery_meta(
            passphrase=secret, quorum_threshold=None, quorum_shares=None, signing_pub=None
        ),
    )
    draw_text = FpdfSurface.draw_text

    def substitute(surface, x, y, text, style):
        if text == secret and (design != "sentinel" or style.family == "Roboto Mono"):
            text = "wrong words"
        draw_text(surface, x, y, text, style)

    with mock.patch.object(FpdfSurface, "draw_text", substitute):
        result = render_frames_to_pdf(inputs)
    assert secret in extract_pdf_text(PdfReader(inputs.output_path))
    with pytest.raises(RenderValidationError, match="recovery passphrase"):
        _validate(inputs, result)


@pytest.mark.parametrize("design", _DESIGNS)
@pytest.mark.parametrize(
    "secret",
    ('1/2 "hello"', "Main frame", "AUTH FRAME", "a" * 600),
    ids=("part-looking-literal", "main-heading", "auth-heading", "oversized-token"),
)
def test_secret_data_is_not_inferred_as_document_structure(
    tmp_path: Path, design: str, secret: str
) -> None:
    inputs = replace(
        _inputs(tmp_path, design, "recovery"),
        recovery_meta=build_recovery_meta(
            passphrase=secret, quorum_threshold=None, quorum_shares=None, signing_pub=None
        ),
    )
    _validate(inputs, render_frames_to_pdf(inputs))


@pytest.mark.parametrize("design", _DESIGNS)
@pytest.mark.parametrize("role", ("main", "kit"))
def test_qr_reading_order_is_required_exclusively_for_kits(
    tmp_path: Path, design: str, role: str
) -> None:
    inputs = _inputs(tmp_path, design, role)
    payloads = inputs.qr_payloads or tuple(encode_frame(frame) for frame in inputs.frames)
    replacements = {payloads[1]: payloads[2], payloads[2]: payloads[1]}
    qr_image = document_inputs.qr_image

    def swap(payload, **kwargs):
        return qr_image(replacements.get(payload, payload), **kwargs)

    with mock.patch.object(document_inputs, "qr_image", swap):
        result = render_frames_to_pdf(inputs)
    if role == "kit":
        with pytest.raises(RenderValidationError, match="kit reading order"):
            _validate(inputs, result)
    else:
        _validate(inputs, result)


@pytest.mark.parametrize("design", _DESIGNS)
def test_kit_rejects_a_duplicated_loader_with_a_consistent_physical_layout(
    tmp_path: Path, design: str
) -> None:
    inputs = _inputs(tmp_path, design, "kit")
    payloads = tuple(inputs.qr_payloads or ())
    expanded_payloads = (payloads[0], *payloads)
    rendered_inputs = replace(
        inputs,
        frames=tuple(
            replace(inputs.frames[0], index=index, total=len(expanded_payloads))
            for index in range(len(expanded_payloads))
        ),
        qr_payloads=expanded_payloads,
    )
    result = render_frames_to_pdf(rendered_inputs)
    assert result.document_summary is not None
    result = replace(
        result,
        document_summary=build_rendered_document_summary(
            inputs,
            encoded_payload_count=len(payloads),
            physical_qr_count=len(expanded_payloads),
            physical_qr_payload_indexes=(0, *range(len(payloads))),
            page_count=result.document_summary.page_count,
            fallback_summary=None,
        ),
    )
    with pytest.raises(RenderValidationError, match="kit reading order"):
        _validate(inputs, result)


@pytest.mark.parametrize("design", _DESIGNS)
@pytest.mark.parametrize("role", ("main", "recovery", "shard", "signing_key_shard", "kit"))
def test_actual_output_matches_inputs(tmp_path: Path, design: str, role: str) -> None:
    inputs = _inputs(tmp_path, design, role)
    _validate(inputs, render_frames_to_pdf(inputs))


def test_blank_pdf_with_original_layouts_and_resources_is_rejected(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path, "sentinel", "main")
    result = render_frames_to_pdf(inputs)
    reader = PdfReader(inputs.output_path)
    writer = PdfWriter()
    for page in reader.pages:
        page[NameObject("/Contents")] = DecodedStreamObject()
        writer.add_page(page)
    writer.write(inputs.output_path)
    with pytest.raises(RenderValidationError, match="painted text"):
        _validate(inputs, result)


def test_unpainted_qr_resources_are_rejected(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path, "sentinel", "main")
    with mock.patch.object(FpdfSurface, "draw_image_bytes"):
        result = render_frames_to_pdf(inputs)
    with pytest.raises(RenderValidationError, match="image paint"):
        _validate(inputs, result)


def test_correct_number_of_wrong_qr_payloads_is_rejected(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path, "sentinel", "main")
    with mock.patch.object(
        document_inputs,
        "qr_image",
        side_effect=lambda payload, **_kwargs: qr_bytes(
            b"wrong:" + hashlib.sha256(payload).digest()
        ),
    ):
        result = render_frames_to_pdf(inputs)
    with pytest.raises(RenderValidationError, match="QR payloads"):
        _validate(inputs, result)


def test_unicode_qr_payload_uses_the_utf8_identity_recorded_in_the_layout(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path, "sentinel", "main")
    inputs = replace(
        inputs,
        frames=(replace(inputs.frames[0], index=0, total=1),),
        qr_payloads=("unicode recovery caf\u00e9 " * 6,),
    )
    _validate(inputs, render_frames_to_pdf(inputs))


@pytest.mark.parametrize("design", _DESIGNS)
def test_white_on_white_qr_is_rejected_before_output(tmp_path: Path, design: str) -> None:
    inputs = replace(
        _inputs(tmp_path, design, "main"), qr_config=QrConfig(dark="white", light="#ffffff")
    )
    with pytest.raises(ValueError, match="darker"):
        render_frames_to_pdf(inputs)
    assert not Path(inputs.output_path).exists()


@pytest.mark.parametrize("design", _DESIGNS)
def test_omitted_passphrase_with_original_layout_is_rejected(tmp_path: Path, design: str) -> None:
    inputs = _inputs(tmp_path, design, "recovery")
    inputs = replace(
        inputs,
        recovery_meta=build_recovery_meta(
            passphrase="violet bronzesecret",
            quorum_threshold=None,
            quorum_shares=None,
            signing_pub=None,
        ),
    )
    draw_text = FpdfSurface.draw_text

    def omit_secret(surface, x, y, text, style):
        if "bronzesecret" not in text:
            draw_text(surface, x, y, text, style)

    with mock.patch.object(FpdfSurface, "draw_text", omit_secret):
        result = render_frames_to_pdf(inputs)
    with pytest.raises(RenderValidationError, match="painted text"):
        _validate(inputs, result)


@pytest.mark.parametrize("design", _DESIGNS)
def test_substituted_passphrase_is_rejected_even_when_line_count_matches(
    tmp_path: Path, design: str
) -> None:
    inputs = replace(
        _inputs(tmp_path, design, "recovery"),
        recovery_meta=build_recovery_meta(
            passphrase="violet bronzesecret",
            quorum_threshold=None,
            quorum_shares=None,
            signing_pub=None,
        ),
    )
    draw_text = FpdfSurface.draw_text

    def substitute(surface, x, y, text, style):
        draw_text(surface, x, y, text.replace("bronzesecret", "wrongsecret"), style)

    with mock.patch.object(FpdfSurface, "draw_text", substitute):
        result = render_frames_to_pdf(inputs)
    with pytest.raises(RenderValidationError, match="recovery passphrase"):
        _validate(inputs, result)


@pytest.mark.parametrize("design", _DESIGNS)
@pytest.mark.parametrize(
    "value,error", (("2 of 3", "recovery quorum"), ("7373", "signing public key"))
)
def test_missing_recovery_metadata_value_is_rejected(
    tmp_path: Path, design: str, value: str, error: str
) -> None:
    inputs = replace(
        _inputs(tmp_path, design, "recovery"),
        recovery_meta=build_recovery_meta(
            passphrase=None,
            quorum_threshold=2,
            quorum_shares=3,
            signing_pub=b"s" * 32,
        ),
    )
    draw_text = FpdfSurface.draw_text

    def omit_value(surface, x, y, text, style):
        draw_text(surface, x, y, text.replace(value, ""), style)

    with mock.patch.object(FpdfSurface, "draw_text", omit_value):
        result = render_frames_to_pdf(inputs)
    with pytest.raises(RenderValidationError, match=error):
        _validate(inputs, result)


@pytest.mark.parametrize("design", _DESIGNS)
@pytest.mark.parametrize(
    "secret",
    (
        pytest.param(
            " ".join(f"word{number:04d}" for number in range(300)), id="literal-continuation"
        ),
        pytest.param('  quotes " and \\ escapes\nwith unicode \u00e9 ' * 20, id="json-parts"),
    ),
)
def test_lossless_passphrase_continuations_validate(
    tmp_path: Path, design: str, secret: str
) -> None:
    inputs = _inputs(tmp_path, design, "recovery")
    inputs = replace(
        inputs,
        recovery_meta=build_recovery_meta(
            passphrase=secret, quorum_threshold=None, quorum_shares=None, signing_pub=b"s" * 32
        ),
    )
    _validate(inputs, render_frames_to_pdf(inputs))


def test_document_and_layout_page_counts_are_required_without_fallback(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path, "sentinel", "main")
    result = render_frames_to_pdf(inputs)
    with pytest.raises(RenderValidationError, match="layout report"):
        _validate(inputs, replace(result, layout_report=None))
    assert result.document_summary is not None
    with pytest.raises(RenderValidationError, match="page count"):
        _validate(
            inputs,
            replace(result, document_summary=replace(result.document_summary, page_count=999)),
        )


@pytest.mark.parametrize("design", _DESIGNS)
@pytest.mark.parametrize("role", ("shard", "signing_key_shard"))
def test_threshold_one_security_copy_matches_actual_recovery(
    tmp_path: Path, design: str, role: str
) -> None:
    private, public = generate_signing_keypair()
    if role == "shard":
        secret = "a single shard recovers this secret"
        payloads = sharding.split_passphrase(
            secret, threshold=1, shares=2, doc_hash=b"h" * 32, sign_priv=private, sign_pub=public
        )
        assert sharding.recover_passphrase([payloads[0]]) == secret
        expected = "this shard alone can recover the secret"
    else:
        payloads = sharding.split_signing_seed(
            private, threshold=1, shares=2, doc_hash=b"h" * 32, sign_priv=private, sign_pub=public
        )
        assert sharding.recover_signing_seed([payloads[0]]) == private
        expected = "this shard alone can recover the signing key"
    frame = Frame(
        VERSION,
        FrameType.KEY_DOCUMENT,
        b"d" * DOC_ID_LEN,
        0,
        1,
        sharding.encode_shard_payload(payloads[0]),
    )
    inputs = replace(
        _inputs(tmp_path, design, role),
        frames=(frame,),
        context={"shard_index": 1, "shard_total": 2, "shard_threshold": 1},
        fallback_sections=(FallbackSection("SHARD PAYLOAD", frame),),
    )
    for origin in ("root_backup", "rebuilt_backup", "replacement_recovery"):
        variant = replace(inputs, origin=DocumentOrigin(kind=origin))
        result = render_frames_to_pdf(variant)
        _validate(variant, result)
        text = " ".join(extract_pdf_text(PdfReader(variant.output_path)).lower().split())
        assert expected in text
        assert "alone is insufficient" not in text
        assert "single shard cannot" not in text
        assert "threshold protected" not in text
        if role == "signing_key_shard":
            assert "this shard alone can authorize future extensions" in text


def test_qr_matrix_compares_identity_multiplicity_and_kit_order() -> None:
    assert not baselines.qr_payloads_match((b"expected",), (b"wrong",))
    assert not baselines.qr_payloads_match((b"a", b"a", b"b"), (b"a", b"b", b"b"))
    assert not baselines.qr_payloads_match((b"shell", b"chunk"), (b"chunk", b"shell"), ordered=True)
    assert baselines.qr_payloads_match((b"a", b"b"), (b"b", b"a"))


def test_matrix_rejects_correct_count_of_wrong_payloads_in_actual_pdf(tmp_path: Path) -> None:
    case = baselines.VisualBaselineCase("sentinel", "main", "A4")
    with mock.patch.object(
        document_inputs,
        "qr_image",
        side_effect=lambda payload, **_kwargs: qr_bytes(
            b"wrong:" + hashlib.sha256(payload).digest()
        ),
    ):
        rendered = baselines.render_baseline(
            case,
            "direct",
            tmp_path,
            rasterize="never",
            raster_dpi=144,
            renderer=render_frames_to_pdf,
        )
    assert rendered.decoded_qr_count == rendered.expected_qr_count
    assert rendered.qr_scan_succeeded is False
    if rendered.composited_qr_scan_skipped_reason is None:
        assert rendered.composited_decoded_qr_count == rendered.expected_qr_count
        assert rendered.composited_qr_scan_succeeded is False


@pytest.mark.parametrize("design", _DESIGNS)
@pytest.mark.parametrize("codec,size", (("raw", 2048), ("base64", 1660)))
def test_near_capacity_main_payloads_decode_from_whole_pages(
    tmp_path: Path, design: str, codec: str, size: int
) -> None:
    inputs = _inputs(tmp_path, design, "main")
    frame = replace(
        inputs.frames[0], index=0, total=1, data=hashlib.shake_256(b"capacity").digest(size)
    )
    payload = encode_qr_payload(encode_frame(frame), codec=codec)
    inputs = replace(inputs, frames=(frame,), qr_payloads=(payload,))
    result = render_frames_to_pdf(inputs)
    _validate(inputs, result)
    decoded, reason = baselines.scan_composited_pdf_qr_payloads(Path(inputs.output_path), dpi=300)
    if reason:
        pytest.skip(reason)
    expected = payload.encode("ascii") if isinstance(payload, str) else payload
    assert decoded == (expected,)
