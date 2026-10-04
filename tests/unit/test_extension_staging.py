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

from __future__ import annotations

import os
import shutil
from dataclasses import replace
from pathlib import Path
from unittest import mock

import pytest

from ethernity.extensions.staging import (
    StagedExtensionPaths,
    create_extension_staging_paths,
    preflight_extension_publish_target,
    validate_staged_extension_dir,
)


def _paths(output_dir: Path, *, index: int = 6) -> StagedExtensionPaths:
    return create_extension_staging_paths(
        output_dir,
        index=index,
        doc_id_hex="deadbeefcafebabe",
        nonce="abc123",
    )


def _populate(paths: StagedExtensionPaths) -> None:
    for path in (paths.qr_document_path, paths.recovery_document_path):
        path.write_bytes(b"placeholder")


def test_output_is_the_selected_destination_with_private_sibling_staging(tmp_path: Path) -> None:
    output_dir = tmp_path / "chosen-name"
    paths = _paths(output_dir)
    assert paths.final_dir == output_dir
    assert paths.staging_dir.parent == output_dir.parent
    assert paths.staging_dir.is_dir()
    assert paths.staging_dir.name.startswith(".staging-")
    if os.name != "nt":
        assert paths.staging_dir.stat().st_mode & 0o777 == 0o700
    assert not output_dir.exists()
    assert not (tmp_path / "extensions").exists()
    assert not (tmp_path / ".chain.lock").exists()
    assert paths.qr_document_path.name == "qr_document-06-deadbeefcafebabe.pdf"
    assert paths.recovery_document_path.name == "recovery_document-06-deadbeefcafebabe.pdf"


def test_large_index_affects_only_conventional_document_names(tmp_path: Path) -> None:
    paths = _paths(tmp_path / "summer-update", index=100)
    assert paths.final_dir.name == "summer-update"
    assert paths.qr_document_path.name == "qr_document-100-deadbeefcafebabe.pdf"


def test_preflight_accepts_missing_parents_without_writing(tmp_path: Path) -> None:
    output_dir = tmp_path / "missing" / "parent" / "update"
    preflight_extension_publish_target(output_dir)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("kind", ["file", "directory", "symlink", "dangling-symlink"])
def test_existing_output_is_never_accepted(tmp_path: Path, kind: str) -> None:
    output_dir = tmp_path / "update"
    if kind == "file":
        output_dir.write_bytes(b"user content")
    elif kind == "directory":
        output_dir.mkdir()
    else:
        target = tmp_path / "target"
        if kind == "symlink":
            target.mkdir()
        output_dir.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="output directory already exists"):
        preflight_extension_publish_target(output_dir)
    with pytest.raises(ValueError, match="output directory already exists"):
        _paths(output_dir)
    assert not any("extension-" in path.name for path in tmp_path.iterdir())


def test_preflight_rejects_a_file_as_output_parent(tmp_path: Path) -> None:
    parent = tmp_path / "parent"
    parent.write_bytes(b"user content")
    with pytest.raises(ValueError, match="output parent must be a directory"):
        preflight_extension_publish_target(parent / "update")


def test_preflight_rejects_a_symlink_as_output_parent(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    parent = tmp_path / "parent"
    parent.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="output parent must not be a symlink"):
        preflight_extension_publish_target(parent / "update")


def test_preflight_rejects_an_unwritable_output_parent(tmp_path: Path) -> None:
    with (
        mock.patch("ethernity.extensions.staging.os.access", return_value=False),
        pytest.raises(ValueError, match="output parent is not writable"),
    ):
        preflight_extension_publish_target(tmp_path / "update")
    assert list(tmp_path.iterdir()) == []


def test_staging_creation_may_create_output_parents(tmp_path: Path) -> None:
    paths = _paths(tmp_path / "new" / "parent" / "update")
    assert paths.staging_dir.parent == tmp_path / "new" / "parent"
    assert paths.staging_dir.is_dir()
    assert not paths.final_dir.exists()


def test_inventory_validation_accepts_explicit_names_without_parsing(tmp_path: Path) -> None:
    original = _paths(tmp_path / "arbitrary-name")
    paths = replace(
        original,
        qr_document_path=original.staging_dir / "scan-carrier.pdf",
        recovery_document_path=original.staging_dir / "text-carrier.pdf",
    )
    _populate(paths)
    validate_staged_extension_dir(paths)


@pytest.mark.parametrize("document", ["qr_document_path", "recovery_document_path"])
def test_inventory_validation_rejects_a_missing_document(tmp_path: Path, document: str) -> None:
    paths = _paths(tmp_path / "update")
    _populate(paths)
    getattr(paths, document).unlink()
    with pytest.raises(ValueError, match="missing required documents"):
        validate_staged_extension_dir(paths)


@pytest.mark.parametrize("kind", ["file", "directory", "symlink"])
def test_inventory_validation_rejects_unplanned_entries(tmp_path: Path, kind: str) -> None:
    paths = _paths(tmp_path / "update")
    _populate(paths)
    unexpected = paths.staging_dir / "unexpected"
    if kind == "file":
        unexpected.write_bytes(b"incidental output")
    elif kind == "directory":
        unexpected.mkdir()
    else:
        unexpected.symlink_to(paths.qr_document_path)
    with pytest.raises(ValueError, match="unexpected|symlinked"):
        validate_staged_extension_dir(paths)


def test_inventory_validation_rejects_a_symlinked_document(tmp_path: Path) -> None:
    paths = _paths(tmp_path / "update")
    _populate(paths)
    paths.qr_document_path.unlink()
    paths.qr_document_path.symlink_to(paths.recovery_document_path)
    with pytest.raises(ValueError, match="symlinked file"):
        validate_staged_extension_dir(paths)


def test_validation_rejects_replaced_staging_directory(tmp_path: Path) -> None:
    paths = _paths(tmp_path / "update")
    _populate(paths)
    parked = tmp_path / "parked-stage"
    paths.staging_dir.rename(parked)
    shutil.copytree(parked, paths.staging_dir)
    with pytest.raises(ValueError, match="staging directory changed"):
        validate_staged_extension_dir(paths)


def test_validation_rejects_replaced_output_parent(tmp_path: Path) -> None:
    parent = tmp_path / "parent"
    parent.mkdir()
    paths = _paths(parent / "update")
    _populate(paths)
    parent.rename(tmp_path / "parked-parent")
    shutil.copytree(tmp_path / "parked-parent", parent)
    stat_result = paths.staging_dir.stat()
    paths = replace(paths, staging_dir_identity=(stat_result.st_dev, stat_result.st_ino))
    with pytest.raises(ValueError, match="output parent changed"):
        validate_staged_extension_dir(paths)


def test_invalid_naming_inputs_do_not_create_staging(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="doc_id_hex"):
        create_extension_staging_paths(tmp_path / "update", index=1, doc_id_hex="bad", nonce="a")
    with pytest.raises(ValueError, match="nonce"):
        create_extension_staging_paths(
            tmp_path / "update", index=1, doc_id_hex="deadbeefcafebabe", nonce="../escape"
        )
    assert list(tmp_path.iterdir()) == []
