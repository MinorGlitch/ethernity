#!/usr/bin/env bash
set -euo pipefail

python -m pip install --upgrade pip
python -m pip install ".[build]"
pyinstaller --clean --noconfirm ethernity.spec
