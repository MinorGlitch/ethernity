"""Standalone kit publication preserves the destination until validation succeeds."""

from dataclasses import replace
from pathlib import Path

import pytest
from pypdf import PdfReader

from ethernity.config import AppConfig
from ethernity.qr.codec import QrConfig
from ethernity.render.checks import RenderValidationError
from ethernity.workflows.kit.service import render_kit_qr_document

_CONFIG = AppConfig(
    design_name="sentinel", paper_size="A4", qr_config=QrConfig(), qr_chunk_size=1024
)


def _create_kit(path: Path, *, config: AppConfig | None = None, renderer=None):
    return render_kit_qr_document(
        output_path=path,
        config=config or _CONFIG,
        variant="lean",
        chunk_size=1200,
        bundle_loader=lambda **_kwargs: b"test bundle",
        payload_builder=lambda *_args: [b"shell", b"chunk-one", b"chunk-two"],
        render_pdf=renderer,
    )


@pytest.mark.parametrize("existing", (False, True))
@pytest.mark.parametrize("failure", ("paint", "validation"))
def test_failed_kit_preserves_destination_and_cleans_staging(
    tmp_path: Path, existing: bool, failure: str
) -> None:
    destination = tmp_path / "kit.pdf"
    if existing:
        _create_kit(destination)
    original = destination.read_bytes() if existing else None

    def fail_after_write(inputs):
        Path(inputs.output_path).write_bytes(b"partial PDF")
        raise OSError("paint failed")

    if failure == "paint":
        with pytest.raises(OSError, match="paint failed"):
            _create_kit(destination, renderer=fail_after_write)
    else:
        config = replace(_CONFIG, qr_config=QrConfig(dark="#fefefe", light="white"))
        with pytest.raises(RenderValidationError, match="no usable QR"):
            _create_kit(destination, config=config)

    assert (destination.read_bytes() if destination.exists() else None) == original
    assert set(tmp_path.iterdir()) == ({destination} if existing else set())


def test_validated_kit_replaces_existing_output(tmp_path: Path) -> None:
    destination = tmp_path / "kit.pdf"
    destination.write_bytes(b"previous contents")
    result = _create_kit(destination)
    assert result.output_path == destination
    assert result.chunk_count == 3
    assert len(PdfReader(destination).pages) > 0
    assert set(tmp_path.iterdir()) == {destination}
