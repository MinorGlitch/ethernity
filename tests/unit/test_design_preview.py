"""Design samples use the production renderer and cannot resemble a real backup."""

import pytest
from pypdf import PdfReader

from ethernity.page_sizes import resolve_paper_size
from ethernity.render.designs import list_design_definitions
from ethernity.tasks.design_preview import create_design_preview


@pytest.mark.parametrize("design", list_design_definitions())
def test_preview_uses_selected_design_and_page_size_without_overwriting_open_pdf(
    tmp_path, design: str
) -> None:
    paper = resolve_paper_size("A4")
    path = create_design_preview(design, paper, tmp_path)
    with path.open("rb") as opened:
        original = opened.read()
        assert create_design_preview(design, paper, tmp_path) == path
        opened.seek(0)
        assert opened.read() == original
    reader = PdfReader(path)
    assert len(reader.pages) == 1
    page = reader.pages[0]
    assert "SAMPLE - NOT A BACKUP" in page.extract_text()
    assert float(page.mediabox.width) == pytest.approx(paper.width_mm * 72 / 25.4, abs=0.1)
    assert float(page.mediabox.height) == pytest.approx(paper.height_mm * 72 / 25.4, abs=0.1)
    assert list(tmp_path.iterdir()) == [path]


def test_failed_preview_leaves_no_partial_files(tmp_path) -> None:
    with pytest.raises(ValueError):
        create_design_preview("not-a-design", resolve_paper_size("A4"), tmp_path)
    assert not list(tmp_path.iterdir())
