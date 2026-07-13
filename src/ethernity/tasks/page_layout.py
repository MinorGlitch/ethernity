"""Task-boundary preflight for design, document, and physical page combinations."""

from __future__ import annotations

from ethernity.page_sizes import PaperSize
from ethernity.render.designs import (
    load_design_manifest_by_name,
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


def require_workflow_page_size(
    design_name: str,
    paper_size: str,
    *,
    candidate_doc_types: frozenset[str],
) -> PaperSize:
    """Require a registered page to support every document this workflow can emit."""

    manifest = load_design_manifest_by_name(design_name)
    selected_doc_types = manifest.documents & candidate_doc_types
    if not selected_doc_types:
        raise ValueError(
            f"design {manifest.name!r} supports none of the workflow document types: "
            f"{', '.join(sorted(candidate_doc_types))}"
        )
    return require_supported_paper_size(
        manifest.name,
        paper_size,
        doc_types=selected_doc_types,
    )


__all__ = [
    "BACKUP_RENDER_DOC_TYPES",
    "KIT_RENDER_DOC_TYPES",
    "require_workflow_page_size",
]
