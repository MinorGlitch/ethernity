import ast
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont

from ethernity.render.checks import validate_pdf_has_pages
from ethernity.render.direct_pdf.components import TextAlign, TextBox
from ethernity.render.direct_pdf.surface import FpdfSurface
from ethernity.render.direct_pdf.text_fit import TextFitError, TextFitPolicy
from ethernity.render.direct_pdf.types import PdfRect, TextStyle

_DIRECT_PDF_ROOT = (
    Path(__file__).resolve().parents[2] / "src" / "ethernity" / "render" / "direct_pdf"
)
_MINIMUM_TEXT_FONT_SIZE_PT = 6.0


def _is_font_size_config_name(name: str | None) -> bool:
    return name is not None and name.endswith("_pt") and "spacing" not in name.lower()


def _numeric_config_values(node: ast.expr) -> tuple[float, ...]:
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return (float(node.value),)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return tuple(-value for value in _numeric_config_values(node.operand))
    if isinstance(node, ast.IfExp):
        return (*_numeric_config_values(node.body), *_numeric_config_values(node.orelse))
    return ()


def _assigned_names(node: ast.Assign | ast.AnnAssign) -> tuple[str, ...]:
    targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
    return tuple(target.id for target in targets if isinstance(target, ast.Name))


class TestDirectPdfTextBox(unittest.TestCase):
    def setUp(self) -> None:
        self.surface = FpdfSurface(page_width_mm=100, page_height_mm=100)
        self.style = TextStyle(family="Helvetica", size_pt=10)

    def test_plan_wraps_text_and_records_non_overflow_layout(self) -> None:
        box = TextBox(
            component_id="instructions",
            text="Record all segment labels for this document set.",
            style=self.style,
            policy=TextFitPolicy.WRAP,
        )

        plan = box.plan(self.surface, PdfRect(10, 10, 32, 25))

        self.assertEqual(plan.component_id, "instructions")
        self.assertGreater(len(plan.lines), 1)
        self.assertFalse(plan.layout.overflow)
        self.assertEqual(plan.layout.overflow_line_count, 0)
        self.assertLessEqual(plan.layout.used_rect.width_mm, 32)
        self.assertLessEqual(plan.layout.used_rect.height_mm, 25)
        for line in plan.lines:
            self.assertGreaterEqual(line.x_mm, 10)
            self.assertLessEqual(line.x_mm + line.width_mm, 42)

    def test_plan_split_policy_keeps_overflow_lines_out_of_paint_plan(self) -> None:
        box = TextBox(
            component_id="fallback",
            text="AUTH MAIN SECTION CONTINUES ACROSS PAGES",
            style=self.style,
            policy=TextFitPolicy.SPLIT,
        )

        plan = box.plan(self.surface, PdfRect(0, 0, 18, self.surface.line_height(self.style)))

        self.assertEqual(len(plan.lines), 1)
        self.assertTrue(plan.layout.overflow)
        self.assertGreater(plan.layout.overflow_line_count, 0)
        self.assertEqual(len(plan.fit.overflow_lines), plan.layout.overflow_line_count)

    def test_plan_rejects_box_that_cannot_fit_one_line(self) -> None:
        box = TextBox(component_id="tiny", text="Nope", style=self.style)

        with self.assertRaisesRegex(TextFitError, "text box height cannot fit one line"):
            box.plan(self.surface, PdfRect(0, 0, 30, 0.1))

    def test_shrink_retries_height_that_cannot_fit_starting_size(self) -> None:
        box = TextBox(
            component_id="shrink-height",
            text="hello",
            style=TextStyle(family="Helvetica", size_pt=20),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6,
        )
        plan = box.plan(self.surface, PdfRect(0, 0, 50, 7))
        self.assertLess(plan.fit.style.size_pt, 20)
        self.assertLessEqual(plan.fit.height_mm, 7)

    def test_shrink_retries_character_too_wide_at_starting_size(self) -> None:
        box = TextBox(
            component_id="shrink-width",
            text="W",
            style=TextStyle(family="Helvetica", size_pt=12),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6,
        )
        plan = box.plan(self.surface, PdfRect(0, 0, 3, 10))
        self.assertLess(plan.fit.style.size_pt, 12)
        self.assertLessEqual(plan.fit.width_mm, 3)

    def test_shrink_recalculates_line_capacity_at_each_size(self) -> None:
        box = TextBox(
            component_id="shrink-lines",
            text="first\nsecond\nthird",
            style=TextStyle(family="Helvetica", size_pt=12),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6,
        )
        plan = box.plan(self.surface, PdfRect(0, 0, 50, 9))
        self.assertEqual(len(plan.lines), 3)
        self.assertLessEqual(plan.fit.height_mm, 9)

    def test_descender_ink_is_contained_and_recorded_in_layout(self) -> None:
        font_path = (
            _DIRECT_PDF_ROOT.parents[1]
            / "resources/designs/_shared/assets/fonts/RobotoMono-Regular.ttf"
        )
        self.surface.register_ttf_font("Roboto Mono", font_path)
        style = TextStyle(family="Roboto Mono", size_pt=12)
        rect = PdfRect(10, 10, 40, 5)
        plan = TextBox(
            component_id="descenders", text="gypq", style=style, line_height_multiplier=1.0
        ).plan(self.surface, rect)
        with TTFont(font_path) as font:
            glyph_set = font.getGlyphSet()
            pens = []
            for character in "gypq":
                pen = BoundsPen(glyph_set)
                glyph_set[font.getBestCmap()[ord(character)]].draw(pen)
                pens.append(pen)
            scale = style.size_pt * 25.4 / 72 / font["head"].unitsPerEm
            ink_top = plan.lines[0].baseline_y_mm - max(pen.bounds[3] for pen in pens) * scale
            ink_bottom = plan.lines[0].baseline_y_mm - min(pen.bounds[1] for pen in pens) * scale
        self.assertGreaterEqual(ink_top, rect.y_mm)
        self.assertLessEqual(ink_bottom, rect.bottom_mm)
        self.assertAlmostEqual(plan.layout.used_rect.y_mm, ink_top)
        self.assertAlmostEqual(plan.layout.used_rect.bottom_mm, ink_bottom)

    def test_plan_rejects_zero_width_box(self) -> None:
        box = TextBox(component_id="zero-width", text="Nope", style=self.style)

        with self.assertRaisesRegex(ValueError, "text box width must be positive"):
            box.plan(self.surface, PdfRect(0, 0, 0, 10))

    def test_rejects_configured_style_below_six_point_floor(self) -> None:
        with self.assertRaisesRegex(ValueError, "style size must be at least 6.0 points"):
            TextBox(
                component_id="unreadable-style",
                text="Too small",
                style=TextStyle(family="Helvetica", size_pt=5.99),
            )

    def test_rejects_shrink_minimum_below_six_point_floor(self) -> None:
        with self.assertRaisesRegex(ValueError, "minimum size must be at least 6.0 points"):
            TextBox(
                component_id="unreadable-minimum",
                text="Too small after shrinking",
                style=self.style,
                policy=TextFitPolicy.SHRINK,
                min_size_pt=5.99,
            )

    def test_accepts_exact_six_point_style_and_shrink_minimum(self) -> None:
        box = TextBox(
            component_id="readable-boundary",
            text="Readable boundary",
            style=TextStyle(family="Helvetica", size_pt=6.0),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        )

        plan = box.plan(self.surface, PdfRect(0, 0, 40, 10))

        self.assertGreaterEqual(plan.layout.font_size_pt, 6.0)

    def test_all_direct_pdf_font_size_literals_respect_six_point_floor(self) -> None:
        violations: list[str] = []
        for path in sorted(_DIRECT_PDF_ROOT.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                for name, value in _font_size_literals(node):
                    if value < _MINIMUM_TEXT_FONT_SIZE_PT:
                        violations.append(
                            f"{path.relative_to(_DIRECT_PDF_ROOT)}:{node.lineno} {name}={value:g}pt"
                        )

        self.assertEqual(violations, [])

    def test_static_floor_scanner_includes_theme_dataclass_tokens(self) -> None:
        for name in (
            "top_strip_min_pt",
            "header_meta_min_pt",
            "footer_min_pt",
            "body_small_pt",
            "section_title_pt",
        ):
            with self.subTest(name=name):
                self.assertTrue(_is_font_size_config_name(name))
        self.assertFalse(_is_font_size_config_name("page_margin_mm"))

    def test_center_alignment_positions_line_inside_rect(self) -> None:
        box = TextBox(
            component_id="centered",
            text="Centered",
            style=self.style,
            policy=TextFitPolicy.FAIL,
            align=TextAlign.CENTER,
        )
        rect = PdfRect(10, 10, 60, 20)

        plan = box.plan(self.surface, rect)
        line = plan.lines[0]

        self.assertGreater(line.x_mm, rect.x_mm)
        self.assertLess(line.x_mm + line.width_mm, rect.right_mm)
        self.assertAlmostEqual(plan.layout.used_rect.x_mm, line.x_mm)
        self.assertAlmostEqual(plan.layout.used_rect.right_mm, line.x_mm + line.width_mm)

    def test_right_alignment_records_the_actual_used_horizontal_bounds(self) -> None:
        box = TextBox(
            component_id="right-aligned",
            text="Right",
            style=self.style,
            policy=TextFitPolicy.FAIL,
            align=TextAlign.RIGHT,
        )
        rect = PdfRect(10, 10, 60, 20)

        plan = box.plan(self.surface, rect)
        line = plan.lines[0]

        self.assertAlmostEqual(plan.layout.used_rect.x_mm, line.x_mm)
        self.assertAlmostEqual(plan.layout.used_rect.right_mm, rect.right_mm)

    def test_paint_writes_valid_pdf(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "text_box.pdf"
            self.surface.add_page()
            box = TextBox(
                component_id="title",
                text="Direct PDF TextBox",
                style=TextStyle(family="Helvetica", size_pt=14),
                policy=TextFitPolicy.FAIL,
            )

            plan = box.plan(self.surface, PdfRect(10, 10, 70, 20))
            plan.paint(self.surface)
            self.surface.output(output_path)

            validate_pdf_has_pages(output_path)


if __name__ == "__main__":
    unittest.main()


def _font_size_literals(node: ast.AST) -> list[tuple[str, float]]:
    configured_values: list[tuple[str, float]] = []
    if isinstance(node, ast.keyword) and _is_font_size_config_name(node.arg):
        configured_values.extend(
            (node.arg or "", value) for value in _numeric_config_values(node.value)
        )
    elif isinstance(node, ast.Assign | ast.AnnAssign):
        value_node = node.value
        if value_node is not None:
            for name in _assigned_names(node):
                if _is_font_size_config_name(name):
                    configured_values.extend(
                        (name, value) for value in _numeric_config_values(value_node)
                    )
    elif isinstance(node, ast.FunctionDef):
        configured_values.extend(_function_font_size_literals(node))
    return configured_values


def _function_font_size_literals(node: ast.FunctionDef) -> list[tuple[str, float]]:
    configured_values: list[tuple[str, float]] = []
    positional = (*node.args.posonlyargs, *node.args.args)
    default_names = positional[len(positional) - len(node.args.defaults) :]
    for argument, default in zip(default_names, node.args.defaults, strict=True):
        if _is_font_size_config_name(argument.arg):
            configured_values.extend(
                (argument.arg, value) for value in _numeric_config_values(default)
            )
    for argument, default in zip(
        node.args.kwonlyargs,
        node.args.kw_defaults,
        strict=True,
    ):
        if default is not None and _is_font_size_config_name(argument.arg):
            configured_values.extend(
                (argument.arg, value) for value in _numeric_config_values(default)
            )
    return configured_values
