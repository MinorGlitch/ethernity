from __future__ import annotations

from pathlib import Path

import segno
from PIL import Image

from ethernity.qr.scan import scan_qr_payloads


def test_real_qr_image_is_decoded_through_disposable_worker(tmp_path: Path) -> None:
    image_path = tmp_path / "untrusted-scan.png"
    segno.make("bounded-worker-payload", error="h").save(image_path, scale=10)

    assert scan_qr_payloads((image_path,)) == [b"bounded-worker-payload"]


def test_real_qr_pdf_is_parsed_through_disposable_worker(tmp_path: Path) -> None:
    image_path = tmp_path / "qr.png"
    pdf_path = tmp_path / "untrusted-scan.pdf"
    segno.make("bounded-pdf-worker-payload", error="h").save(image_path, scale=10)
    with Image.open(image_path) as image:
        image.convert("RGB").save(pdf_path, "PDF")

    assert scan_qr_payloads((pdf_path,)) == [b"bounded-pdf-worker-payload"]
