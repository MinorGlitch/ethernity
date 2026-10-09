"""Validated page artwork and content slots used by PDF templates."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Color = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]
Positive = Annotated[float, Field(gt=0)]
NonNegative = Annotated[float, Field(ge=0)]
Rectangle = tuple[float, float, NonNegative, NonNegative]


class TemplateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)


class LayoutTextStyle(TemplateModel):
    family: str
    size_pt: float = Field(ge=6)
    style: Literal["", "B", "I", "BI"] = ""
    color: Color
    char_spacing_pt: float = Field(default=0, ge=0)


class LayoutElement(TemplateModel):
    """One measured component, with optional bindings to document content."""

    key: str
    kind: Literal["text", "panel", "rule", "ellipse", "image", "line", "group"]
    box: Rectangle
    ref: str | None = None
    after: str | None = None
    gap_after: NonNegative = 0
    repeat: int = Field(default=1, ge=1, le=200)
    step: tuple[float, float] = (0, 0)
    text: str = ""
    style: str | None = None
    stroke: Color | None = None
    fill: Color | None = None
    line_width: float = Field(default=0.2, gt=0)
    radius: float = Field(default=0, ge=0)
    align: Literal["left", "center", "right"] = "left"
    fit: Literal["fail", "wrap", "shrink"] = "fail"
    min_size: float = Field(default=6, ge=6)
    max_lines: int | None = Field(default=None, ge=1)
    line_height: float = Field(default=1.2, gt=0)
    font_size: Annotated[float, Field(ge=6)] | None = None
    stretch_x: bool = False
    stretch_y: bool = False
    scale_height: bool = False
    metadata: (
        Literal["recovery_passphrase", "recovery_quorum", "recovery_signing_public_key"] | None
    ) = None
    value_prefix: str = ""
    visible: str | None = None
    line: tuple[float, float, float, float] | None = None
    qr_slot: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_component(self) -> Self:
        if self.kind == "text" and not self.style:
            raise ValueError("text requires a named style")
        if self.kind == "line" and self.line is None:
            raise ValueError("line requires endpoints")
        if self.kind == "group" and not self.ref:
            raise ValueError("group requires a component reference")
        return self


class GridArtwork(TemplateModel):
    box: Rectangle
    columns: int = Field(ge=1)
    rows: int = Field(ge=1)
    card_size: tuple[Positive, Positive]
    gap: tuple[NonNegative, NonNegative]
    horizontal: Literal["start", "center", "space_between"] = "start"
    vertical: Literal["start", "center", "space_between"] = "start"
    reserve_rows: bool = False
    background: Color | None = None
    border: Color | None = None
    rule: Color | None = None
    border_width: float = 0.45
    grid_step: Positive = 22
    padding: float = 2


class PageArtwork(TemplateModel):
    elements: tuple[LayoutElement, ...]
    qr_capacity: int = Field(default=0, ge=0)
    grid: GridArtwork | None = None
    inventory: InventoryArtwork | None = None


class DocumentArtwork(TemplateModel):
    first: PageArtwork
    continuation: PageArtwork | None = None
    trailing: tuple[PageArtwork, ...] = ()
    recovery: RecoveryArtwork | None = None
    sheet: SheetFallback | None = None


class DocumentReference(TemplateModel):
    use: str


class Template(TemplateModel):
    """Artwork is template data; pagination and payload handling remain shared."""

    reference_size: tuple[Positive, Positive] = (210, 297)
    styles: dict[str, LayoutTextStyle]
    documents: dict[str, DocumentArtwork | DocumentReference]
    components: dict[str, tuple[LayoutElement, ...]] = Field(default_factory=dict)

    def document(self, name: str) -> DocumentArtwork:
        """Documents may share composition while keeping their own typed content and copy."""
        visited: set[str] = set()
        while True:
            if name in visited:
                raise ValueError(f"cyclic document layout: {name}")
            visited.add(name)
            if name not in self.documents:
                raise ValueError(f"unknown document layout: {name}")
            document = self.documents[name]
            if isinstance(document, DocumentArtwork):
                return document
            name = document.use

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        for node in _nodes(self.model_dump()):
            _validate_flow_references(node)
            for key, value in node.items():
                if (key == "style" or key.endswith("_style")) and value and "family" not in node:
                    if value not in self.styles:
                        raise ValueError(f"unknown text style: {value}")
            if node.get("kind") == "group" and node["ref"] not in self.components:
                raise ValueError(f"unknown component: {node['ref']}")
        for name in self.components:
            self._check_component_cycle(name, ())
        for name in self.documents:
            self.document(name)
        return self

    def _check_component_cycle(self, name: str, ancestors: tuple[str, ...]) -> None:
        if name in ancestors:
            raise ValueError(f"cyclic component reference: {name}")
        for element in self.components[name]:
            if element.ref:
                self._check_component_cycle(element.ref, (*ancestors, name))


def _nodes(value: object) -> Iterator[dict]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _nodes(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _nodes(child)


def _validate_flow_references(node: dict) -> None:
    for sequence in node.values():
        if not isinstance(sequence, (tuple, list)):
            continue
        preceding: set[str] = set()
        for element in sequence:
            if not isinstance(element, dict) or "kind" not in element:
                continue
            if element.get("after") and element["after"] not in preceding:
                raise ValueError(
                    f"flow reference must name a preceding element: {element['after']}"
                )
            preceding.add(element["key"])


class FallbackProfile(TemplateModel):
    box: Rectangle
    row_height: float = Field(gt=0)
    body_style: str
    number_style: str
    left: float = 0
    right: float = 0
    reserved: float = 0
    number_gap: float = 0
    number_width: float = 0
    number_maximum_width: Positive | None = None
    number_padding: float = 0
    inline_number: bool = False
    safety: float = 0.2
    columns: int = Field(default=1, ge=1, le=2)
    column_gap: float = 0
    fill_rows: bool = False
    title: tuple[LayoutElement, ...] = ()
    row: tuple[LayoutElement, ...]
    section: tuple[LayoutElement, ...] = ()
    empty: tuple[LayoutElement, ...] = ()


class PassphraseLayout(TemplateModel):
    page: PageArtwork
    style: str
    guidance_style: str
    width: float
    height: float
    continuation_box: Rectangle
    line_height: float = 1.15
    single_line: bool = False


class RecoveryArtwork(TemplateModel):
    first: FallbackProfile
    continuation: FallbackProfile
    passphrase: PassphraseLayout
    metadata: MetadataArtwork | None = None
    section_gap_rows: int = Field(default=0, ge=0)


class HeaderField(TemplateModel):
    name: str
    label: str
    x: float
    width: float
    y: float = 0
    label_style: str
    value_style: str
    placement: Literal["above", "beside", "prefix", "value"] = "above"
    minimum_height: float = 4
    label_line_height: float = 1.2
    label_height: float = 0
    label_width: float = 0
    label_gap: float = 0
    padding: float = 0
    top_padding: float = 0
    bottom_padding: float = 0
    line_height: float = 1.12
    uppercase: bool = False
    align: Literal["left", "right"] = "left"
    stroke: Color | None = None
    fill: Color | None = None
    line_width: float = 0.35


class MetadataArtwork(TemplateModel):
    flow: Literal["columns", "stack", "boxes"]
    box: Rectangle
    reference_bottom: float
    gap: float = 1.2
    bottom_anchor: bool = False
    repeat_on_continuation: bool = True
    quorum_in_header: bool = False
    heading_height: float = 0
    fields: tuple[HeaderField, ...] = ()
    label_style: str
    value_style: str
    guidance_style: str
    border: Color = "#bbbbbb"
    fill: Color = "#ffffff"
    label_height: float = 4.8
    box_offset: float = 5.2
    minimum_height: float = 7.8
    padding: float = 3
    measurement_padding: float = 2.2
    bottom_inset: float = 0
    label_right_inset: float = 0
    line_width: float = 0.2
    line_height: float = 1.2
    shift_start: float = 0
    shift_end: float = 0
    minimum_bottom: float = 0


class SheetDensity(TemplateModel):
    columns: int = Field(default=1, ge=1, le=2)
    row_height: float = Field(gt=0)
    font_size: float = Field(ge=6)
    title_size: float = Field(ge=6)
    title_height: Positive | None = None
    row_gap: float = Field(default=0, ge=0)

    @property
    def title_extra_height(self) -> float:
        return max(0, (self.title_height or self.row_height) - self.row_height)


class SheetFallback(TemplateModel):
    balanced_columns: bool = False
    box: Rectangle
    bottom_anchor: bool = True
    qr_area_top: NonNegative | None = None
    qr_bottom_gap: NonNegative | None = None
    padding: float = 0
    payload_inset: float = 0
    column_gap: float = 4
    top: float = 0
    bottom: float = 0
    safety: float = 0.2
    numbering: Literal["none", "inline", "separate"] = "separate"
    body_style: str
    profiles: tuple[SheetDensity, ...]
    decoration: tuple[LayoutElement, ...] = ()
    title: tuple[LayoutElement, ...]
    row: tuple[LayoutElement, ...]
    hatch: Color | None = None
    hatch_step: Positive = 2.75
    hatch_inset: float = 0.6


class InventoryArtwork(TemplateModel):
    top: float
    row_height: Positive
    capacity: int = Field(ge=1)
    row: tuple[LayoutElement, ...]
