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

"""Validate rendered PDF content, layout, and appearance."""

from __future__ import annotations

from collections import Counter

from ethernity.encoding.framing import encode_frame
from ethernity.render.checks import (
    RenderValidationError,
    validate_fallback_summary,
    validate_fallback_text_in_pdf,
    validate_layout_report,
    validate_pdf_has_pages,
    validate_rendered_document_summary,
    validate_text_in_pdf,
)
from ethernity.render.doc_types import DOC_TYPE_KIT
from ethernity.render.pdf_appearance import validate_pdf_appearance
from ethernity.render.pdf_content import validate_painted_content
from ethernity.render.recovery_meta import (
    PASSPHRASE_PRINT_MODE_LITERAL,
    RecoveryMeta,
    decode_printed_passphrase,
)
from ethernity.render.types import (
    LayoutReport,
    RenderedDocumentSummary,
    RenderInputs,
    RenderResult,
)


def validate_rendered_pdf_document(
    *,
    inputs: RenderInputs,
    result: object,
    document_label: str,
    expected_text: tuple[str, ...] = (),
) -> None:
    """Validate a renderer result, its summary metadata, and its emitted PDF."""

    if not isinstance(result, RenderResult):
        raise RenderValidationError(
            f"{document_label} renderer did not return RenderResult",
            details={"result_type": type(result).__name__},
        )
    document_summary = result.document_summary
    if document_summary is None:
        raise RenderValidationError(f"{document_label} is missing rendered document summary")
    validate_rendered_document_summary(
        document_label=document_label,
        inputs=inputs,
        document_summary=document_summary,
    )
    reader = validate_pdf_has_pages(inputs.output_path, document_label=document_label)
    if inputs.render_fallback:
        fallback_sections = tuple(inputs.fallback_sections or ())
        fallback_summary = document_summary.fallback_summary or result.fallback_summary
        validate_fallback_summary(
            document_label=document_label,
            frames=tuple(section.frame for section in fallback_sections),
            fallback_summary=fallback_summary,
        )
        validate_fallback_text_in_pdf(
            document_label=document_label,
            reader=reader,
            fallback_sections=fallback_sections,
            fallback_summary=fallback_summary,
        )
    if document_summary.page_count != len(reader.pages):
        raise RenderValidationError(
            f"{document_label} document summary page count does not match the PDF file"
        )
    validate_layout_report(
        document_label=document_label,
        layout_report=result.layout_report,
        expected_page_count=len(reader.pages),
    )
    if result.layout_report is None:
        raise RenderValidationError(f"{document_label} is missing render layout report")
    validate_painted_content(
        reader=reader, layout_report=result.layout_report, document_label=document_label
    )
    decoded = validate_pdf_appearance(
        path=inputs.output_path,
        layout_report=result.layout_report,
        render_qr=inputs.render_qr,
        document_label=document_label,
    )
    _validate_emitted_qr_payloads(inputs, document_summary, decoded, document_label)
    if inputs.recovery_meta is not None:
        _validate_recovery_metadata_in_pdf(
            inputs=inputs, layout=result.layout_report, document_label=document_label
        )
    if expected_text:
        validate_text_in_pdf(
            document_label=document_label,
            reader=reader,
            expected_text=expected_text,
            details_key="missing_component_ids",
            missing_message=f"{document_label} is missing expected inventory rows",
        )


def _validate_emitted_qr_payloads(
    inputs: RenderInputs,
    document_summary: RenderedDocumentSummary,
    decoded: tuple[bytes, ...],
    document_label: str,
) -> None:
    if inputs.render_qr:
        expected_payloads = expected_physical_qr_payloads(inputs, document_summary)
        if Counter(decoded) != Counter(expected_payloads):
            raise RenderValidationError(f"{document_label} QR payloads do not match render inputs")
        if inputs.doc_type == DOC_TYPE_KIT and (
            document_summary.physical_qr_payload_indexes
            != tuple(range(document_summary.encoded_payload_count))
            or decoded != expected_payloads
        ):
            raise RenderValidationError(
                f"{document_label} QR payloads are not in kit reading order"
            )


def expected_physical_qr_payloads(
    inputs: RenderInputs, document_summary: RenderedDocumentSummary
) -> tuple[bytes, ...]:
    """Resolve the exact payload bytes for each recorded physical QR placement."""

    payloads = inputs.qr_payloads
    if payloads is None:
        payloads = tuple(encode_frame(frame) for frame in inputs.frames)
    encoded = tuple(
        payload.encode("utf-8") if isinstance(payload, str) else payload for payload in payloads
    )
    return tuple(encoded[index] for index in document_summary.physical_qr_payload_indexes)


def _validate_recovery_metadata_in_pdf(
    *, inputs: RenderInputs, layout: LayoutReport, document_label: str
) -> None:
    """Decode only verified value placements, using the pagination's explicit print mode."""

    meta = inputs.recovery_meta
    if meta is None:
        return
    values = _recovery_value_placements(layout, document_label)
    quorum = values.get("recovery_quorum", {}).get(0)
    if meta.quorum_value and (quorum is None or " ".join(quorum[1]) != meta.quorum_value):
        raise RenderValidationError(
            f"{document_label} is missing or has an incorrect recovery quorum"
        )
    signing = values.get("recovery_signing_public_key", {}).get(0)
    if meta.signing_pub_lines and (
        signing is None
        or "".join("".join(signing[1]).split()) != "".join("".join(meta.signing_pub_lines).split())
    ):
        raise RenderValidationError(
            f"{document_label} is missing or has an incorrect recovery signing public key"
        )
    if not meta.passphrase and not meta.passphrase_lines:
        return
    passphrase = values.get("recovery_passphrase", {})
    if not passphrase or list(passphrase) != list(range(len(passphrase))):
        raise RenderValidationError(f"{document_label} is missing recovery passphrase placements")
    modes = {value[0] for value in passphrase.values()}
    if len(modes) != 1 or None in modes:
        raise RenderValidationError(
            f"{document_label} has inconsistent recovery passphrase print modes"
        )
    _validate_printed_passphrase_value(meta, passphrase, document_label)


def _validate_printed_passphrase_value(
    meta: RecoveryMeta,
    passphrase: dict[int, tuple[str | None, tuple[str, ...]]],
    document_label: str,
) -> None:
    print_mode = passphrase[0][0]
    if print_mode is None:
        raise RenderValidationError(
            f"{document_label} is missing the recovery passphrase print mode"
        )
    lines = tuple(line for index in sorted(passphrase) for line in passphrase[index][1])
    try:
        decoded = decode_printed_passphrase(lines, print_mode=print_mode)
        expected = meta.passphrase
        if expected is None:
            expected = decode_printed_passphrase(
                meta.passphrase_lines, print_mode=meta.passphrase_print_mode
            )
    except ValueError as exc:
        raise RenderValidationError(
            f"{document_label} has incomplete recovery passphrase parts"
        ) from exc
    if decoded != expected:
        raise RenderValidationError(f"{document_label} has an incorrect recovery passphrase")


def _recovery_value_placements(
    layout: LayoutReport, document_label: str
) -> dict[str, dict[int, tuple[str | None, tuple[str, ...]]]]:
    values: dict[str, dict[int, tuple[str | None, tuple[str, ...]]]] = {}
    for page in layout.pages:
        for component in page.components:
            metadata = component.text_metadata
            if metadata is None:
                continue
            lines = tuple(line.text for line in component.text_lines)
            if metadata.value_prefix:
                text = " ".join(lines)
                if not text.startswith(metadata.value_prefix):
                    raise RenderValidationError(
                        f"{document_label} has incorrect recovery value structure"
                    )
                lines = (text[len(metadata.value_prefix) :],)
            if (
                metadata.print_mode == PASSPHRASE_PRINT_MODE_LITERAL
                or metadata.role == "recovery_quorum"
            ):
                lines = (" ".join(lines),)
            elif metadata.role == "recovery_signing_public_key":
                lines = ("".join("".join(lines).split()),)
            value = (metadata.print_mode, lines)
            copies = values.setdefault(metadata.role, {})
            previous = copies.setdefault(metadata.continuation_index, value)
            if previous != value:
                raise RenderValidationError(
                    f"{document_label} has inconsistent repeated recovery values"
                )

    return values


__all__ = ["expected_physical_qr_payloads", "validate_rendered_pdf_document"]
