# -*- mode: python ; coding: utf-8 -*-
import sys
import tomllib
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    copy_metadata,
)

hiddenimports = (
    ["textual.widgets._markdown_viewer", "textual.widgets._tab_pane", "textual.drivers.web_driver"]
    + collect_submodules("rich._unicode_data")
    + collect_submodules("zxingcpp")
)
datas = collect_data_files("ethernity") + copy_metadata("ethernity-paper")
datas += copy_metadata("textual-serve")
datas += collect_data_files("pypdfium2", includes=["version.json"])
datas += collect_data_files("pypdfium2_raw", includes=["version.json"])
binaries = collect_dynamic_libs("pypdfium2_raw")


a = Analysis(
    ["src/ethernity/__main__.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ethernity",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
)

desktop_exes = []
if sys.platform in {"win32", "darwin"}:
    desktop_exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="ethernity-desktop",
        console=False,
        icon="images/readme_logo.png",
        strip=False,
        upx=True,
        argv_emulation=False,
    )
    if sys.platform == "win32":
        desktop_exes.append(desktop_exe)

coll = COLLECT(
    exe,
    *desktop_exes,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ethernity",
)

if sys.platform == "darwin":
    version = tomllib.loads((Path(SPECPATH) / "pyproject.toml").read_text())["project"]["version"]
    app = BUNDLE(
        desktop_exe,
        [("ethernity", exe.name, "EXECUTABLE"), *a.binaries, *a.datas],
        name="Ethernity.app",
        icon="images/readme_logo.png",
        bundle_identifier="org.minorglitch.ethernity",
        version=version,
        info_plist={
            "LSUIElement": True,
            "NSHighResolutionCapable": True,
            "CFBundleDisplayName": "Ethernity",
        },
    )
