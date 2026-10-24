"""The upgrade fixture must install an older executable and an obsolete command."""

from __future__ import annotations

import hashlib
import tarfile

from scripts.check_homebrew_upgrade import OBSOLETE_COMMAND, OLD_VERSION, old_formula


def test_old_release_fixture_has_verified_executables(tmp_path):
    formula = old_formula(tmp_path)
    archive = tmp_path / f"ethernity-{OLD_VERSION}.tar.gz"
    assert archive.as_uri() in formula
    assert hashlib.sha256(archive.read_bytes()).hexdigest() in formula
    assert f'version "{OLD_VERSION}"' in formula
    with tarfile.open(archive) as stream:
        for name in ("ethernity", OBSOLETE_COMMAND):
            member = stream.getmember(f"ethernity-{OLD_VERSION}/{name}")
            assert member.mode & 0o111 == 0o111
            script = stream.extractfile(member)
            assert script is not None
            assert script.read() == f"#!/bin/sh\nprintf 'ethernity {OLD_VERSION}\\n'\n".encode()
            assert f'"{name}"' in formula
