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

"""Helpers for extension directory naming and operator-facing artifact filenames."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ethernity.core.bounds import MAX_EXTENSION_INDEX
from ethernity.crypto.sharding import MAX_SHARES
from ethernity.encoding.framing import DOC_ID_LEN

_DOC_ID_HEX_RE = re.compile(rf"^[0-9a-f]{{{DOC_ID_LEN * 2}}}$")
_CANONICAL_EXTENSION_DIR_RE = re.compile(r"^(0[1-9]|[1-9][0-9]{1,})$")
_STAGING_DIR_RE = re.compile(r"^\.staging-(?P<index>[1-9][0-9]*)-(?P<nonce>[A-Za-z0-9._-]+)$")
_MAIN_ARTIFACT_RE = re.compile(
    r"^(?P<doc_type>qr_document|recovery_document|recovery_kit|recovery_kit_index)"
    r"-(?P<index>0[1-9]|[1-9][0-9]{1,})-(?P<doc_id>[0-9a-f]{16})\.pdf$"
)
_SHARD_ARTIFACT_RE = re.compile(
    r"^(?P<doc_type>shard|signing-key-shard)"
    r"-(?P<index>0[1-9]|[1-9][0-9]{1,})-(?P<doc_id>[0-9a-f]{16})"
    r"-(?P<share_index>[1-9][0-9]*)-of-(?P<share_count>[1-9][0-9]*)\.pdf$"
)


@dataclass(frozen=True)
class ExtensionMainArtifactName:
    doc_type: str
    index: int
    doc_id_hex: str


@dataclass(frozen=True)
class ExtensionShardArtifactName:
    doc_type: str
    index: int
    doc_id_hex: str
    share_index: int
    share_count: int


def canonical_extension_dir_name(index: int) -> str:
    index_value = _require_extension_index(index)
    return f"{index_value:02d}" if index_value < 100 else str(index_value)


def loose_extension_dir_name(index: int, doc_id_hex: str) -> str:
    index_value = canonical_extension_dir_name(index)
    doc_id_value = _require_doc_id_hex(doc_id_hex)
    return f"extension-{index_value}-{doc_id_value}"


def parse_extension_dir_name(name: str) -> int:
    if not is_canonical_extension_dir_name(name):
        raise ValueError(f"invalid extension directory name: {name}")
    return _require_extension_index(int(name, 10))


def is_canonical_extension_dir_name(name: str) -> bool:
    if _CANONICAL_EXTENSION_DIR_RE.fullmatch(name) is None:
        return False
    return int(name, 10) <= MAX_EXTENSION_INDEX


def build_staging_dir_name(index: int, nonce: str) -> str:
    index_value = _require_extension_index(index)
    nonce_value = _require_staging_nonce(nonce)
    return f".staging-{index_value}-{nonce_value}"


def is_staging_dir_name(name: str) -> bool:
    return bool(_STAGING_DIR_RE.fullmatch(name))


def build_extension_main_filename(doc_type: str, index: int, doc_id_hex: str) -> str:
    doc_type_value = _require_main_doc_type(doc_type)
    index_value = canonical_extension_dir_name(index)
    doc_id_value = _require_doc_id_hex(doc_id_hex)
    return f"{doc_type_value}-{index_value}-{doc_id_value}.pdf"


def parse_extension_main_filename(filename: str) -> ExtensionMainArtifactName:
    match = _MAIN_ARTIFACT_RE.fullmatch(filename)
    if match is None:
        raise ValueError(f"invalid extension main artifact filename: {filename}")
    return ExtensionMainArtifactName(
        doc_type=match.group("doc_type"),
        index=_require_extension_index(int(match.group("index"), 10)),
        doc_id_hex=match.group("doc_id"),
    )


def build_extension_shard_filename(
    doc_type: str,
    index: int,
    doc_id_hex: str,
    *,
    share_index: int,
    share_count: int,
) -> str:
    doc_type_value = _require_shard_doc_type(doc_type)
    index_value = canonical_extension_dir_name(index)
    doc_id_value = _require_doc_id_hex(doc_id_hex)
    share_index_value = _require_share_number(share_index, label="share_index")
    share_count_value = _require_share_number(share_count, label="share_count")
    if share_index_value > share_count_value:
        raise ValueError("share_index must be less than or equal to share_count")
    return (
        f"{doc_type_value}-{index_value}-{doc_id_value}"
        f"-{share_index_value}-of-{share_count_value}.pdf"
    )


def parse_extension_shard_filename(filename: str) -> ExtensionShardArtifactName:
    match = _SHARD_ARTIFACT_RE.fullmatch(filename)
    if match is None:
        raise ValueError(f"invalid extension shard artifact filename: {filename}")
    share_index = int(match.group("share_index"), 10)
    share_count = int(match.group("share_count"), 10)
    _require_share_number(share_index, label="share_index")
    _require_share_number(share_count, label="share_count")
    if share_index > share_count:
        raise ValueError("share_index must be less than or equal to share_count")
    return ExtensionShardArtifactName(
        doc_type=match.group("doc_type"),
        index=_require_extension_index(int(match.group("index"), 10)),
        doc_id_hex=match.group("doc_id"),
        share_index=share_index,
        share_count=share_count,
    )


def _require_extension_index(value: int) -> int:
    index_value = _require_positive_int(value, label="index")
    if index_value > MAX_EXTENSION_INDEX:
        raise ValueError(f"index must be <= MAX_EXTENSION_INDEX ({MAX_EXTENSION_INDEX})")
    return index_value


def _require_share_number(value: int, *, label: str) -> int:
    share_number = _require_positive_int(value, label=label)
    if share_number > MAX_SHARES:
        raise ValueError(f"{label} must be <= MAX_SHARES ({MAX_SHARES})")
    return share_number


def _require_positive_int(value: int, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    if value <= 0:
        raise ValueError(f"{label} must be greater than 0")
    return value


def _require_doc_id_hex(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("doc_id_hex must be a non-empty string")
    if _DOC_ID_HEX_RE.fullmatch(value) is None:
        raise ValueError(f"doc_id_hex must be {DOC_ID_LEN * 2} lowercase hex characters")
    return value


def _require_staging_nonce(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("nonce must be a non-empty string")
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError("nonce must not contain path separators")
    if _STAGING_DIR_RE.fullmatch(f".staging-1-{value}") is None:
        raise ValueError("nonce contains unsupported characters")
    return value


def _require_main_doc_type(value: str) -> str:
    if value not in {"qr_document", "recovery_document", "recovery_kit", "recovery_kit_index"}:
        raise ValueError(f"unsupported extension main doc_type: {value}")
    return value


def _require_shard_doc_type(value: str) -> str:
    if value not in {"shard", "signing-key-shard"}:
        raise ValueError(f"unsupported extension shard doc_type: {value}")
    return value
