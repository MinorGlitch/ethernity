"""Small immutable value types used by direct PDF rendering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FontStyle = Literal["", "B", "I", "BI"]


def _validate_non_negative(value: float, *, field_name: str) -> None:
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")


@dataclass(frozen=True)
class PdfColor:
    """An RGB color used by the direct PDF surface."""

    red: int
    green: int
    blue: int

    def __post_init__(self) -> None:
        for field_name, value in (
            ("red", self.red),
            ("green", self.green),
            ("blue", self.blue),
        ):
            if not 0 <= value <= 255:
                raise ValueError(f"{field_name} must be between 0 and 255")


BLACK = PdfColor(0, 0, 0)


@dataclass(frozen=True)
class PdfRect:
    """A rectangle in millimeters."""

    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float

    def __post_init__(self) -> None:
        _validate_non_negative(self.width_mm, field_name="width_mm")
        _validate_non_negative(self.height_mm, field_name="height_mm")

    @property
    def right_mm(self) -> float:
        return self.x_mm + self.width_mm

    @property
    def bottom_mm(self) -> float:
        return self.y_mm + self.height_mm


@dataclass(frozen=True)
class TextStyle:
    """Font selection and text color for measured PDF text."""

    family: str
    size_pt: float
    style: FontStyle = ""
    color: PdfColor = BLACK
    char_spacing_mm: float = 0.0

    def __post_init__(self) -> None:
        if not self.family.strip():
            raise ValueError("family must be non-empty")
        if self.size_pt <= 0:
            raise ValueError("size_pt must be positive")
        _validate_non_negative(self.char_spacing_mm, field_name="char_spacing_mm")
