# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    copy_metadata,
)

hiddenimports = (
    ["textual.widgets._markdown_viewer", "textual.widgets._tab_pane"]
    + collect_submodules("rich._unicode_data")
    + collect_submodules("zxingcpp")
)
datas = collect_data_files("ethernity") + copy_metadata("ethernity-paper")
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

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ethernity",
)
