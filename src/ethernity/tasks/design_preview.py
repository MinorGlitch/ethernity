"""Render a labelled sample with the same engine used for backup documents."""

from __future__ import annotations

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType
from ethernity.page_sizes import PaperSize
from ethernity.render.backend_dispatch import render_frames_to_pdf
from ethernity.render.doc_types import DOC_TYPE_MAIN
from ethernity.render.types import DocumentOrigin, RenderInputs


def create_design_preview(design: str, paper: PaperSize, directory: Path) -> Path:
    """Keep samples in the app cache, never writing into a user's backup folder."""
    directory.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="render-", dir=directory) as scratch:
        sample = Path(scratch) / "sample.pdf"
        render_frames_to_pdf(
            RenderInputs(
                frames=(
                    Frame(
                        version=VERSION,
                        frame_type=FrameType.MAIN_DOCUMENT,
                        doc_id=b"\x00" * DOC_ID_LEN,
                        index=0,
                        total=1,
                        data=b"DESIGN PREVIEW - NOT A BACKUP",
                    ),
                ),
                output_path=sample,
                context={
                    "doc_id": "SAMPLE - NOT A BACKUP",
                    "created_timestamp_utc": "2026-01-01 00:00 UTC",
                },
                doc_type=DOC_TYPE_MAIN,
                origin=DocumentOrigin(kind="root_backup"),
                design_name=design,
                page_size=paper,
                render_fallback=False,
            )
        )
        data = sample.read_bytes()
    digest = hashlib.sha256(data).hexdigest()[:16]
    path = directory / f"design-preview-{digest}.pdf"
    try:
        # Do not replace a PDF that is already open in a viewer on Windows.
        with path.open("xb") as output:
            output.write(data)
    except FileExistsError:
        pass
    return path
