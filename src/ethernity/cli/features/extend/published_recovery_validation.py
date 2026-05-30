#!/usr/bin/env python3
# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>.

"""Published extension recovery-document artifact validation."""

from __future__ import annotations

from pathlib import Path

from ethernity.cli.shared import api_codes
from ethernity.cli.shared.ndjson import ApiCommandError
from ethernity.render.proofs import RenderProofError, validate_pdf_has_pages


def validate_published_recovery_document_carrier(
    *,
    path: Path,
) -> None:
    try:
        validate_pdf_has_pages(
            path,
            artifact_label=f"published recovery document {path.name}",
        )
    except ApiCommandError:
        raise
    except RenderProofError as exc:
        raise ApiCommandError(
            code=api_codes.EXTENSION_MAIN_CARRIER_INVALID,
            message=str(exc),
            details=exc.details,
        ) from exc
    except Exception as exc:
        raise ApiCommandError(
            code=api_codes.EXTENSION_MAIN_CARRIER_INVALID,
            message=f"published recovery document {path.name} is invalid: {exc}",
        ) from exc


__all__ = [
    "validate_published_recovery_document_carrier",
]
