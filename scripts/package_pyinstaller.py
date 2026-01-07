#!/usr/bin/env python3
from __future__ import annotations

import os
import zipfile
from pathlib import Path


def main() -> None:
    dist = Path("dist")
    if not dist.exists():
        raise SystemExit("dist/ not found; run PyInstaller first")
    runner_os = os.environ.get("RUNNER_OS", "local")
    output = Path(f"ethernity-{runner_os}.zip")
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in dist.glob("ethernity*"):
            if path.is_dir():
                for file in path.rglob("*"):
                    zf.write(file, file.relative_to(dist))
            else:
                zf.write(path, path.name)
    print(f"Created {output}")


if __name__ == "__main__":
    main()
