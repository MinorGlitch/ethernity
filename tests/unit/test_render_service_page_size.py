from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from ethernity.config import AppConfig
from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType
from ethernity.qr.codec import QrConfig
from ethernity.render.service import RenderService
from ethernity.render.types import RenderLineage


def _service(*, paper_size: str = "Letter") -> RenderService:
    config = SimpleNamespace(
        paper_size=paper_size,
        design_name="archive",
        qr_config=QrConfig(),
        cli_defaults=SimpleNamespace(runtime=SimpleNamespace(render_jobs=None)),
    )
    return RenderService(config=cast(AppConfig, cast(Any, config)))


def _frame() -> Frame:
    return Frame(
        version=VERSION,
        frame_type=FrameType.MAIN_DOCUMENT,
        doc_id=b"\x42" * DOC_ID_LEN,
        index=0,
        total=1,
        data=b"typed-page-size",
    )


class TestRenderServicePageSize(unittest.TestCase):
    def test_render_inputs_carry_one_typed_normalized_page_size(self) -> None:
        inputs = _service().qr_inputs(
            (_frame(),),
            Path("ignored.pdf"),
            lineage=RenderLineage(kind="root_backup"),
        )

        assert inputs.page_size is not None
        self.assertEqual(inputs.page_size.name, "LETTER")
        self.assertEqual(inputs.page_size.display_name, "Letter")
        self.assertEqual(inputs.context["paper_size"], "LETTER")
        self.assertAlmostEqual(inputs.page_size.width_mm, 215.9)
        self.assertAlmostEqual(inputs.page_size.height_mm, 279.4)

    def test_render_context_cannot_override_configured_page_size(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot override configured paper size"):
            _service().base_context({"paper_size": "A4"})

    def test_same_page_name_in_different_case_is_normalized(self) -> None:
        context = _service().base_context({"paper_size": " letter "})

        self.assertEqual(context["paper_size"], "LETTER")


if __name__ == "__main__":
    unittest.main()
