"""Central registry of named physical paper sizes."""

from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Mapping, TypeAlias

PaperSizeName: TypeAlias = str

A4_WIDTH_MM = 210.0
A4_HEIGHT_MM = 297.0
LETTER_WIDTH_MM = 215.9
LETTER_HEIGHT_MM = 279.4


@dataclass(frozen=True)
class PaperSize:
    """A named portrait paper size in physical millimeters."""

    name: PaperSizeName
    display_name: str
    width_mm: float
    height_mm: float

    def __post_init__(self) -> None:
        normalized = self.name.strip().upper()
        if not normalized:
            raise ValueError("paper size name must be non-empty")
        if normalized != self.name:
            raise ValueError("paper size name must be normalized uppercase")
        if any(character.isspace() for character in self.name):
            raise ValueError("paper size name must be whitespace-free")
        if not self.display_name.strip():
            raise ValueError("paper size display_name must be non-empty")
        if self.display_name.strip() != self.display_name:
            raise ValueError("paper size display_name must not have surrounding whitespace")
        for field_name, value in (("width_mm", self.width_mm), ("height_mm", self.height_mm)):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{field_name} must be finite and positive")
        if self.height_mm <= self.width_mm:
            raise ValueError("paper size dimensions must describe portrait geometry")


DEFAULT_PAPER_SIZE_NAME: Final[PaperSizeName] = "A4"

_REGISTERED_PAPER_SIZES: Final[tuple[PaperSize, ...]] = (
    PaperSize(
        name="A4",
        display_name="A4",
        width_mm=A4_WIDTH_MM,
        height_mm=A4_HEIGHT_MM,
    ),
    PaperSize(
        name="LETTER",
        display_name="Letter",
        width_mm=LETTER_WIDTH_MM,
        height_mm=LETTER_HEIGHT_MM,
    ),
)

PAPER_SIZES: Final[Mapping[str, PaperSize]] = MappingProxyType(
    {paper.name: paper for paper in _REGISTERED_PAPER_SIZES}
)
if len(PAPER_SIZES) != len(_REGISTERED_PAPER_SIZES):
    raise RuntimeError("registered paper size names must be unique")
if DEFAULT_PAPER_SIZE_NAME not in PAPER_SIZES:
    raise RuntimeError("default paper size must be registered")


def normalize_paper_size_name(value: str) -> PaperSizeName:
    """Normalize a user-facing paper-size name."""

    return value.strip().upper()


def paper_size_names() -> tuple[PaperSizeName, ...]:
    """Return registered names in stable UI/CLI order."""

    return tuple(PAPER_SIZES)


def paper_size_display_name(value: str) -> str:
    """Return the human-facing label for a registered paper size."""

    return resolve_paper_size(value).display_name


def resolve_paper_size(value: str) -> PaperSize:
    """Resolve a registered paper size or raise an actionable error."""

    normalized = normalize_paper_size_name(value)
    paper = PAPER_SIZES.get(normalized)
    if paper is None:
        choices = ", ".join(paper_size_names())
        raise ValueError(f"unknown paper size {value!r}; registered paper sizes: {choices}")
    return paper


def is_registered_paper_size(value: str) -> bool:
    """Return whether ``value`` names a registered paper size."""

    return normalize_paper_size_name(value) in PAPER_SIZES


__all__ = [
    "A4_HEIGHT_MM",
    "A4_WIDTH_MM",
    "DEFAULT_PAPER_SIZE_NAME",
    "LETTER_HEIGHT_MM",
    "LETTER_WIDTH_MM",
    "PAPER_SIZES",
    "PaperSize",
    "PaperSizeName",
    "is_registered_paper_size",
    "normalize_paper_size_name",
    "paper_size_display_name",
    "paper_size_names",
    "resolve_paper_size",
]
