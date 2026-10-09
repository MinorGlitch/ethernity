"""Preflight design, document, and physical page combinations for task execution."""

from __future__ import annotations

from typing import Annotated, TypeAlias, TypeVar

from pydantic import AfterValidator, BaseModel

from ethernity.page_sizes import PaperSize, PaperSizeName, resolve_paper_size
from ethernity.render.designs import (
    load_design_definition_by_name,
    require_supported_paper_size,
)
from ethernity.render.doc_types import (
    DOC_TYPE_KIT,
    DOC_TYPE_KIT_INDEX,
    DOC_TYPE_MAIN,
    DOC_TYPE_RECOVERY,
    DOC_TYPE_SHARD,
    DOC_TYPE_SIGNING_KEY_SHARD,
)

BACKUP_RENDER_DOC_TYPES = frozenset(
    {
        DOC_TYPE_MAIN,
        DOC_TYPE_RECOVERY,
        DOC_TYPE_SHARD,
        DOC_TYPE_SIGNING_KEY_SHARD,
    }
)
KIT_RENDER_DOC_TYPES = frozenset({DOC_TYPE_KIT, DOC_TYPE_KIT_INDEX})
PrintTask = TypeVar("PrintTask", bound=BaseModel)


def with_print_layout(state: PrintTask, *, paper_size: str | None, design: str | None) -> PrintTask:
    """Validate a complete print choice before replacing either coupled field."""
    candidate = state.model_validate(
        {**state.model_dump(), "paper_size": paper_size, "design": design}
    )
    updates = {
        key: value
        for key, value in candidate.model_dump(include={"paper_size", "design"}).items()
        if value != getattr(state, key)
    }
    return state.model_copy(update=updates)


def _normalize_paper_size(value: str) -> PaperSizeName:
    return resolve_paper_size(value).name


ValidatedPaperSizeName: TypeAlias = Annotated[PaperSizeName, AfterValidator(_normalize_paper_size)]


def require_workflow_page_size(
    design_name: str,
    paper_size: str,
    *,
    candidate_doc_types: frozenset[str],
) -> PaperSize:
    """Require a registered page to support every document this workflow can emit."""

    definition = load_design_definition_by_name(design_name)
    selected_doc_types = definition.documents & candidate_doc_types
    if not selected_doc_types:
        raise ValueError(
            f"design {definition.name!r} supports none of the workflow document types: "
            f"{', '.join(sorted(candidate_doc_types))}"
        )
    return require_supported_paper_size(
        definition.name,
        paper_size,
        doc_types=selected_doc_types,
    )


def validate_backup_print_options(
    design: str | None, paper_size: str | None, qr_chunk_size: int | None
) -> None:
    """Validate an explicit page choice and any custom QR capacity."""
    if design is not None and paper_size is not None:
        require_workflow_page_size(design, paper_size, candidate_doc_types=BACKUP_RENDER_DOC_TYPES)
    if qr_chunk_size is not None and qr_chunk_size < 1:
        raise ValueError("QR chunk size must be positive")


__all__ = [
    "BACKUP_RENDER_DOC_TYPES",
    "KIT_RENDER_DOC_TYPES",
    "ValidatedPaperSizeName",
    "require_workflow_page_size",
    "validate_backup_print_options",
    "with_print_layout",
]
