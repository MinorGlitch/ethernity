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

from __future__ import annotations

import hashlib
import os
import tarfile
import zipfile
from pathlib import Path


def main() -> None:
    dist = Path("dist")
    if not dist.exists():
        raise SystemExit("dist/ not found; run PyInstaller first")
    runner_os = os.environ.get("RUNNER_OS", "local")
    base = f"ethernity-{runner_os}"
    dist_paths = list(dist.glob("ethernity*"))
    if not dist_paths:
        raise SystemExit("no built artifacts found in dist/")

    if runner_os == "Windows":
        output = Path(f"{base}.zip")
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in dist_paths:
                if path.is_dir():
                    for file in path.rglob("*"):
                        zf.write(file, file.relative_to(dist))
                else:
                    zf.write(path, path.name)
    else:
        output = Path(f"{base}.tar.gz")
        with tarfile.open(output, "w:gz") as tf:
            for path in dist_paths:
                if path.is_dir():
                    tf.add(path, arcname=path.relative_to(dist))
                else:
                    tf.add(path, arcname=path.name)

    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    checksum_path = output.with_suffix(output.suffix + ".sha256")
    checksum_path.write_text(f"{digest}  {output.name}\n", encoding="utf-8")
    print(f"Created {output}")
    print(f"Created {checksum_path}")


if __name__ == "__main__":
    main()
