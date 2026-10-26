"""Export desktop icons and the tray animation.

Run with: uv run --with cairosvg python scripts/build_icons.py
CairoSVG and system Cairo are export tools, not application dependencies.
"""

from __future__ import annotations

import io
import math
import xml.etree.ElementTree as ET
from itertools import accumulate
from pathlib import Path

import cairosvg
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
IMAGES = ROOT / "images"
ICONS = ROOT / "src/ethernity/resources/icons"
SVG = "{http://www.w3.org/2000/svg}"
FRAME_COUNT = 120
TRAY_FRAME_STEP = 2
HALF_WIDTH = 72
CREASE_SKEW = 70
# Paper centreline in the editable SVG's coordinates. The short outer verticals
# preserve the clipped corners of the original mark. Segment 2 crosses in front.
POINTS = (
    (135, 565),
    (298, 422),
    (410, 422),
    (844, 837),
    (956, 837),
    (1127, 700),
    (1127, 565),
    (950, 422),
    (842, 422),
    (410, 837),
    (298, 837),
    (135, 700),
)
EDGES = tuple(zip(POINTS, POINTS[1:] + POINTS[:1], strict=True))
LENGTHS = tuple(math.dist(a, b) for a, b in EDGES)
OFFSETS = tuple(accumulate(LENGTHS, initial=0))
LOOP_LENGTH = OFFSETS[-1]
NORMALS = tuple(
    (-(b[1] - a[1]) / length, (b[0] - a[0]) / length)
    for (a, b), length in zip(EDGES, LENGTHS, strict=True)
)
MITERS = tuple(
    (
        (a[0] + b[0]) / (1 + a[0] * b[0] + a[1] * b[1]),
        (a[1] + b[1]) / (1 + a[0] * b[0] + a[1] * b[1]),
    )
    for a, b in zip(NORMALS[-1:] + NORMALS[:-1], NORMALS, strict=True)
)
Point = tuple[float, float]


def clip_crease(polygon: list[Point], segment: int, limit: float, *, above: bool) -> list[Point]:
    """Cut a ribbon panel along an oblique, straight paper crease."""
    result = []
    for previous, current in zip(polygon[-1:] + polygon[:-1], polygon, strict=True):
        before = (
            OFFSETS[segment] + previous[0] * LENGTHS[segment] + previous[1] * CREASE_SKEW - limit
        )
        after = OFFSETS[segment] + current[0] * LENGTHS[segment] + current[1] * CREASE_SKEW - limit
        previous_inside = before >= -1e-7 if above else before <= 1e-7
        current_inside = after >= -1e-7 if above else after <= 1e-7
        if previous_inside != current_inside:
            fraction = before / (before - after)
            result.append(
                tuple(a + fraction * (b - a) for a, b in zip(previous, current, strict=True))
            )
        if current_inside:
            result.append(current)
    return result


def fold_point(segment: int, along: float, across: float, center: float) -> Point:
    """Move a panel's corners as the folded-back section passes through it."""
    a, b = EDGES[segment]
    normal_a, normal_b = MITERS[segment], MITERS[(segment + 1) % len(POINTS)]
    distance = OFFSETS[segment] + along * LENGTHS[segment] + across * CREASE_SKEW - center
    fold = max(0, 1 - abs(distance) / 125)
    shift = (-across * HALF_WIDTH * 0.35 + 20) * fold
    return tuple(
        (a[axis] + normal_a[axis] * across * HALF_WIDTH) * (1 - along)
        + (b[axis] + normal_b[axis] * across * HALF_WIDTH) * along
        + (normal_a[axis] * (1 - along) + normal_b[axis] * along) * shift
        for axis in (0, 1)
    )


def paper_paths(phase: float) -> list[ET.Element]:
    """Two travelling folds, with the crossing drawn above the returning strip.

    Panels have solid fills and straight edges: no lighting, extrusion or glow.
    Half a circuit exchanges the identical folds and closes the visual loop.
    """
    result = []
    for segment in (*range(2), *range(3, len(POINTS)), 2):
        paths: dict[str, list[str]] = {}
        for cycle in range(-1, 3):
            center = (phase + cycle) * LOOP_LENGTH / 2
            bounds = (-LOOP_LENGTH / 4, -125, -72, 0, 100, 125, LOOP_LENGTH / 4)
            for low, high in zip(bounds, bounds[1:], strict=False):
                if (
                    center + high < OFFSETS[segment] - CREASE_SKEW
                    or center + low > OFFSETS[segment + 1] + CREASE_SKEW
                ):
                    continue
                polygon = clip_crease(
                    [(0, -1), (1, -1), (1, 1), (0, 1)], segment, center + low, above=True
                )
                polygon = clip_crease(polygon, segment, center + high, above=False)
                if len(polygon) < 3:
                    continue
                color = "#e0b663" if segment == 2 else "#d8ac59"
                if low == -72:
                    color = "#35372e"
                elif low == 0:
                    color = "#efca78"
                corners = (fold_point(segment, along, across, center) for along, across in polygon)
                path = "M" + "L".join(f"{x:.3f},{y:.3f}" for x, y in corners) + "Z"
                paths.setdefault(color, []).append(path)
        result.extend(
            ET.Element(SVG + "path", {"d": "".join(parts), "fill": color})
            for color, parts in paths.items()
        )
    return result


def render(source: Path, size: tuple[int, int], phase: float | None = None) -> Image.Image:
    root = ET.fromstring(source.read_text(encoding="utf-8"))
    if phase is not None:
        group = root.find(SVG + "g")
        assert group is not None
        group[:] = paper_paths(phase)
    png = cairosvg.svg2png(
        bytestring=ET.tostring(root), output_width=size[0] * 2, output_height=size[1] * 2
    )
    with Image.open(io.BytesIO(png)) as image:
        return image.convert("RGBA").resize(size, Image.Resampling.LANCZOS)


def main() -> None:
    ICONS.mkdir(parents=True, exist_ok=True)
    app_source = IMAGES / "ethernity-app.svg"
    app = render(app_source, (1024, 1024))
    app.save(ICONS / "app.png")
    app.save(IMAGES / "ethernity.ico", sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
    sprite = Image.new("RGBA", (64 * (FRAME_COUNT // TRAY_FRAME_STEP), 64))
    for frame in range(0, FRAME_COUNT, TRAY_FRAME_STEP):
        phase = frame / FRAME_COUNT + 0.14
        sprite.paste(render(app_source, (64, 64), phase), (64 * (frame // TRAY_FRAME_STEP), 0))
    sprite.save(ICONS / "activity.png")


if __name__ == "__main__":
    main()
