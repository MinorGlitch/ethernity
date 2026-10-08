"""Reuse immutable rendering inputs without skipping PDF validation."""

from collections.abc import Callable
from dataclasses import replace
from functools import cache, lru_cache
from pathlib import Path
from shutil import copyfile

import pytest
from scripts.render_visual_baselines import VisualBaselineCase, build_sample_inputs

from ethernity.render import render_frames_to_pdf
from ethernity.render.direct_pdf import document_inputs
from ethernity.render.types import RenderInputs, RenderResult

RenderedSample = Callable[[str, str], tuple[RenderInputs, RenderResult]]


@pytest.fixture(scope="session")
def _qr_images():
    # The complete payload and frozen QrConfig form the cache key. Opt-in layout
    # tests still paint and decode each PDF; codec tests use the uncached function.
    cached = lru_cache(maxsize=256)(document_inputs.qr_image)
    yield cached
    cached.cache_clear()


@pytest.fixture
def reuse_qr_images(monkeypatch, _qr_images):
    monkeypatch.setattr(document_inputs, "qr_image", _qr_images)


@pytest.fixture(scope="session")
def _rendered_samples(tmp_path_factory) -> RenderedSample:
    root = tmp_path_factory.mktemp("rendered-samples")

    @cache
    def render(design: str, role: str) -> tuple[RenderInputs, RenderResult]:
        inputs = build_sample_inputs(
            VisualBaselineCase(design, role, "A4"), root / f"{design}-{role}.pdf"
        )
        return inputs, render_frames_to_pdf(inputs)

    return render


@pytest.fixture
def rendered_sample(tmp_path: Path, _rendered_samples: RenderedSample) -> RenderedSample:
    """Give every caller a private PDF, including tests that deliberately damage it."""
    count = 0

    def copy(design: str, role: str) -> tuple[RenderInputs, RenderResult]:
        nonlocal count
        inputs, result = _rendered_samples(design, role)
        path = tmp_path / f"{design}-{role}-{count}.pdf"
        count += 1
        copyfile(inputs.output_path, path)
        assert result.document_summary is not None
        copied_result = replace(
            result, document_summary=replace(result.document_summary, output_path=str(path))
        )
        return replace(inputs, output_path=path), copied_result

    return copy
